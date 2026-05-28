import threading
import time
import re
from typing import Any, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncssh
import stat
from pathlib import PurePosixPath

from app.config import get_settings
from app.auth_store import AuthenticatedUser
from app.security import get_request_user
from app.ssh_manager import ssh_manager
from app.security import validate_path
from app.metrics import TRANSFER_THROUGHPUT

router = APIRouter(prefix="/files", tags=["Files"])
_SAFE_USER_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# --- Models ---

class FileEntry(BaseModel):
    name: str
    path: str
    size: int
    is_dir: bool
    mtime: int
    permissions: str

class DirectoryListing(BaseModel):
    path: str
    entries: List[FileEntry]

class MkdirRequest(BaseModel):
    path: str

# --- Helpers ---

def _format_file_entry(entry: asyncssh.SFTPName, parent_path: str) -> FileEntry:
    is_dir = stat.S_ISDIR(entry.attrs.permissions)
    # Ensure usage of forward slashes for remote paths
    full_path = str(PurePosixPath(parent_path) / entry.filename)

    return FileEntry(
        name=entry.filename,
        path=full_path,
        size=entry.attrs.size or 0,
        is_dir=is_dir,
        mtime=int(entry.attrs.mtime or 0),
        permissions=stat.filemode(entry.attrs.permissions)
    )


def _safe_user_segment(username: str) -> str:
    text = _SAFE_USER_SEGMENT_RE.sub("_", str(username or "").strip().lower()).strip("._-")
    return text or "user"


def _base_path_for_user(user: AuthenticatedUser, path: str | None = None) -> str:
    root = get_settings().hpc_data_root
    apps_root = get_settings().hpc_apps_root
    if user.is_admin and path and str(path).startswith(str(PurePosixPath(apps_root))):
        return apps_root
    if user.is_admin:
        return root
    return str(PurePosixPath(root) / "users" / _safe_user_segment(user.username))


def _normalize_requested_path(path: str, user: AuthenticatedUser) -> str:
    base_path = _base_path_for_user(user, path)
    if path == "/" or not path:
        return base_path
    return validate_path(path, base_path=base_path)


async def _validate_existing_remote_path(sftp: asyncssh.SFTPClient, path: str, user: AuthenticatedUser) -> str:
    base_path = _base_path_for_user(user, path)
    safe_path = _normalize_requested_path(path, user)
    try:
        real_path = await sftp.realpath(safe_path)
    except asyncssh.SFTPError:
        raise HTTPException(status_code=404, detail="Path not found")
    if not isinstance(real_path, str):
        real_path = safe_path
    return validate_path(str(real_path), base_path=base_path)


async def _validate_remote_parent_for_write(sftp: asyncssh.SFTPClient, path: str, user: AuthenticatedUser) -> str:
    base_path = _base_path_for_user(user, path)
    safe_path = _normalize_requested_path(path, user)
    parent_path = str(PurePosixPath(safe_path).parent)
    try:
        real_parent = await sftp.realpath(parent_path)
    except asyncssh.SFTPError:
        raise HTTPException(status_code=404, detail="Parent directory not found")
    if not isinstance(real_parent, str):
        real_parent = parent_path
    validate_path(str(real_parent), base_path=base_path)
    return safe_path

# --- Endpoints ---

@router.get("/list", response_model=DirectoryListing)
async def list_directory(request: Request, path: str = Query(..., description="Absolute path on HPC")):
    """List contents of a directory on the HPC."""
    try:
        user = get_request_user(request)
        path = _normalize_requested_path(path, user)

        async with await ssh_manager.open_sftp() as sftp:
            path = await _validate_existing_remote_path(sftp, path, user)
            # Check if path exists and is a directory
            try:
                attrs = await sftp.stat(path)
                if not stat.S_ISDIR(attrs.permissions):
                     raise HTTPException(status_code=400, detail="Path is not a directory")
            except asyncssh.SFTPError:
                raise HTTPException(status_code=404, detail="Path not found")

            entries = await sftp.readdir(path)
            # Filter out . and ..
            entries = [e for e in entries if e.filename not in ('.', '..')]

            formatted_entries = [_format_file_entry(e, path) for e in entries]
            # Sort: directories first, then alphabetical
            formatted_entries.sort(key=lambda x: (not x.is_dir, x.name))

            return DirectoryListing(
                path=path,
                entries=formatted_entries
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stat", response_model=FileEntry)
async def get_file_stat(request: Request, path: str = Query(..., description="Absolute path of file")):
    """Get metadata for a single file or directory."""
    try:
        user = get_request_user(request)
        path = _normalize_requested_path(path, user)
        async with await ssh_manager.open_sftp() as sftp:
            path = await _validate_existing_remote_path(sftp, path, user)
            try:
                # We need the filename for the entry, so we split the path
                pp = PurePosixPath(path)

                attrs = await sftp.stat(path)

                return FileEntry(
                    name=pp.name,
                    path=path,
                    size=attrs.size or 0,
                    is_dir=stat.S_ISDIR(attrs.permissions),
                    mtime=int(attrs.mtime or 0),
                    permissions=stat.filemode(attrs.permissions)
                )

            except asyncssh.SFTPError:
                 raise HTTPException(status_code=404, detail="File not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/download")
async def download_file(
    request: Request,
    path: str = Query(..., description="Absolute path to download"),
    range_header: Optional[str] = Header(None, alias="Range")
):
    """
    Stream file content. Supports HTTP Range requests for resumable downloads.
    """
    user = get_request_user(request)
    path = _normalize_requested_path(path, user)
    CHUNK_SIZE = 1024 * 1024  # 1MB chunks

    # 1. Get file size for Range calculations
    try:
        # We need a quick stat first to validate existence and size
        # Ideally we do this inside the stream generator to save a conection,
        # but we need to set headers on the response *before* yielding.
        # So we might need two Ops or one long-lived usage.

        # Let's open SFTP and STAT, then we will construct the generator which re-opens?
        # Or better: The Generator controls the SFTP session.
        # But we need 'size' for Content-Length/Content-Range headers.

        # Strategy: Open SFTP here, do stat.
        # Pass SFTP Client OR create NEW one in generator?
        # AsyncSSH allows multiple channels.

        # To be safe and independent:
        file_size = 0
        async with await ssh_manager.open_sftp() as sftp:
            path = await _validate_existing_remote_path(sftp, path, user)
            attrs = await sftp.stat(path)
            file_size = attrs.size or 0
    except asyncssh.SFTPError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 2. Parse Range Header
    start = 0
    end = file_size - 1
    status_code = 200

    if range_header:
        try:
            # Format: bytes=0-1023
            unit, ranges = range_header.split("=")
            if unit == "bytes":
                r_start, r_end = ranges.split("-")
                start = int(r_start) if r_start else 0
                end = int(r_end) if r_end else file_size - 1
                status_code = 206 # Partial Content
        except ValueError:
            pass # Invalid range, ignore

    # Clamp
    if start >= file_size:
         # Requested range not satisfiable
         return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    end = min(end, file_size - 1)
    content_length = end - start + 1

    # 3. Generator
    async def iter_file():
        try:
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(path, 'rb') as f:
                    if start > 0:
                        await f.seek(start)

                    bytes_remaining = content_length
                    while bytes_remaining > 0:
                        read_size = min(CHUNK_SIZE, bytes_remaining)
                        chunk = await f.read(read_size)
                        if not chunk:
                            break
                        TRANSFER_THROUGHPUT.labels(direction="download").inc(len(chunk))
                        yield chunk
                        bytes_remaining -= len(chunk)
        except Exception as e:
            # Logging would be good here
            print(f"Streaming error: {e}")
            raise

    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(content_length),
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{PurePosixPath(path).name}"'
    }

    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    return StreamingResponse(
        iter_file(),
        status_code=status_code,
        headers=headers
    )

@router.delete("/")
async def delete_item(request: Request, path: str = Query(..., description="Absolute path to delete")):
    """Delete a file or directory (recursive)."""
    try:
        user = get_request_user(request)
        path = _normalize_requested_path(path, user)
        async with await ssh_manager.open_sftp() as sftp:
            path = await _validate_existing_remote_path(sftp, path, user)
            if not await sftp.exists(path):
                raise HTTPException(status_code=404, detail="Path not found")

            is_dir = await sftp.isdir(path)

            if is_dir:
                await sftp.rmtree(path)
            else:
                await sftp.remove(path)

            return {"success": True, "message": f"Deleted {path}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/mkdir")
async def create_directory(request: Request, payload: MkdirRequest):
    """Create a new directory."""
    try:
        user = get_request_user(request)
        path = _normalize_requested_path(payload.path, user)
        async with await ssh_manager.open_sftp() as sftp:
            path = await _validate_remote_parent_for_write(sftp, path, user)
            if await sftp.exists(path):
                raise HTTPException(status_code=409, detail="Path already exists")

            await sftp.makedirs(path)
            return {"success": True, "path": path}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Upload State ---

# Format: {upload_id: {path: str, temp_path: str, owner: str, bytes_written: int, created_at: float, last_activity: float}}
upload_sessions: dict[str, dict[str, Any]] = {}
_upload_sessions_lock = threading.Lock()


def _cleanup_upload_sessions(now: float, ttl_seconds: int) -> None:
    expiry = max(1, int(ttl_seconds))
    expired_ids = [
        upload_id
        for upload_id, session in upload_sessions.items()
        if now - float(session.get("last_activity", session.get("created_at", now))) > expiry
    ]
    for upload_id in expired_ids:
        upload_sessions.pop(upload_id, None)


def _resolve_upload_session(upload_id: str, user: AuthenticatedUser) -> dict[str, Any]:
    settings = get_settings()
    now = time.monotonic()
    with _upload_sessions_lock:
        _cleanup_upload_sessions(now, settings.upload_session_ttl_seconds)
        session = upload_sessions.get(upload_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Upload session not found")
        owner = str(session.get("owner", ""))
        if not user.is_admin and owner != user.username:
            raise HTTPException(status_code=403, detail="Upload session is owned by a different user")
        session["last_activity"] = now
        return dict(session)

class UploadInitRequest(BaseModel):
    path: str

class UploadInitResponse(BaseModel):
    upload_id: str

@router.post("/upload/init", response_model=UploadInitResponse)
async def init_upload(request: Request, payload: UploadInitRequest):
    """Initialize a multipart upload."""
    user = get_request_user(request)
    settings = get_settings()
    requested_path = _normalize_requested_path(payload.path, user)

    import uuid
    upload_id = str(uuid.uuid4())
    safe_path = None
    temp_path = None

    now = time.monotonic()
    with _upload_sessions_lock:
        _cleanup_upload_sessions(now, settings.upload_session_ttl_seconds)
        if len(upload_sessions) >= max(1, int(settings.upload_max_active_sessions)):
            raise HTTPException(status_code=429, detail="Too many active upload sessions")

        active_for_user = sum(
            1 for session in upload_sessions.values() if session.get("owner") == user.username
        )
        if active_for_user >= max(1, int(settings.upload_max_active_sessions_per_user)):
            raise HTTPException(status_code=429, detail="Too many active upload sessions for this user")

        upload_sessions[upload_id] = {
            "path": "",
            "temp_path": "",
            "owner": user.username,
            "bytes_written": 0,
            "created_at": now,
            "last_activity": now,
        }

    # Ensure directory exists and create empty temp file
    try:
        async with await ssh_manager.open_sftp() as sftp:
            safe_path = await _validate_remote_parent_for_write(sftp, requested_path, user)
            temp_path = f"{safe_path}.part"
            # Create/truncate temp file
            async with sftp.open(temp_path, 'w') as f:
                await f.write(b'')
        with _upload_sessions_lock:
            if upload_id in upload_sessions:
                upload_sessions[upload_id]["path"] = safe_path
                upload_sessions[upload_id]["temp_path"] = temp_path

        return UploadInitResponse(upload_id=upload_id)
    except HTTPException:
        with _upload_sessions_lock:
            upload_sessions.pop(upload_id, None)
        raise
    except Exception as e:
        with _upload_sessions_lock:
            upload_sessions.pop(upload_id, None)
        raise HTTPException(status_code=500, detail=f"Failed to init upload: {str(e)}")

@router.put("/upload/{upload_id}")
async def upload_chunk(
    upload_id: str,
    request: Request,
    chunk: bytes = Body(..., media_type="application/octet-stream"),
):
    """Upload a chunk of data. Appends to the temp file."""
    user = get_request_user(request)
    settings = get_settings()
    chunk_len = len(chunk)
    max_chunk = max(1, int(settings.upload_max_chunk_bytes))
    max_file = max(1, int(settings.upload_max_file_bytes))
    if chunk_len > max_chunk:
        raise HTTPException(status_code=413, detail=f"Upload chunk too large (max {max_chunk} bytes)")

    session = _resolve_upload_session(upload_id, user)
    temp_path = session["temp_path"]
    with _upload_sessions_lock:
        live_session = upload_sessions.get(upload_id)
        if live_session is None:
            raise HTTPException(status_code=404, detail="Upload session not found")
        bytes_written = int(live_session.get("bytes_written", 0))
        if bytes_written + chunk_len > max_file:
            raise HTTPException(status_code=413, detail=f"Upload file too large (max {max_file} bytes)")
        live_session["bytes_written"] = bytes_written + chunk_len
        live_session["last_activity"] = time.monotonic()

    try:
        async with await ssh_manager.open_sftp() as sftp:
            # Append mode 'a'
            async with sftp.open(temp_path, 'a') as f:
                await f.write(chunk)

        TRANSFER_THROUGHPUT.labels(direction="upload").inc(len(chunk))

        return {"success": True}
    except Exception as e:
        with _upload_sessions_lock:
            live_session = upload_sessions.get(upload_id)
            if live_session is not None:
                live_session["bytes_written"] = max(0, int(live_session.get("bytes_written", 0)) - chunk_len)
        raise HTTPException(status_code=500, detail=f"Write failed: {str(e)}")

@router.post("/upload/{upload_id}/finish")
async def finish_upload(upload_id: str, request: Request):
    """Finalize the upload by renaming temp file to target path."""
    user = get_request_user(request)
    settings = get_settings()
    session = _resolve_upload_session(upload_id, user)
    temp_path = session["temp_path"]
    target_path = session["path"]

    try:
        async with await ssh_manager.open_sftp() as sftp:
            attrs = await sftp.stat(temp_path)
            file_size = attrs.size or 0
            max_file = max(1, int(settings.upload_max_file_bytes))
            if file_size > max_file:
                await sftp.remove(temp_path)
                with _upload_sessions_lock:
                    upload_sessions.pop(upload_id, None)
                raise HTTPException(status_code=413, detail=f"Upload file too large (max {max_file} bytes)")
            # Atomic rename (posix rename usually replaces)
            await sftp.rename(temp_path, target_path)

        with _upload_sessions_lock:
            upload_sessions.pop(upload_id, None)
        return {"success": True, "path": target_path}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Finalize failed: {str(e)}")
