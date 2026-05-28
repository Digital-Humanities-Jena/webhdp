"""Cloud mirror metadata and availability helpers for user-uploaded artifacts."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from database.database import db
from database.models import CloudMirrorObject, Session as DBSession
from services.cloud_upload_service import (
    CloudUploadService,
    STORAGE_DROPBOX,
    STORAGE_GDRIVE,
    STORAGE_MODE_CLOUD_BACKUP,
    STORAGE_MODE_LOCAL,
    STORAGE_MODE_PURE_CLOUD,
    STORAGE_MODE_SERVER_ONLY,
)

logger = logging.getLogger(__name__)

ARTIFACT_SINGLE_FILE = "source_file"
ARTIFACT_BATCH_ZIP = "batch_zip"
ARTIFACT_MSF = "msf"

MIRROR_STATUS_AVAILABLE = "available"
MIRROR_STATUS_FAILED = "failed"
MIRROR_STATUS_PENDING = "pending"

CLOUD_STORAGE_PROVIDERS = {STORAGE_DROPBOX, STORAGE_GDRIVE}
CLOUD_MIRROR_STORAGE_MODES = {STORAGE_MODE_PURE_CLOUD, STORAGE_MODE_CLOUD_BACKUP}


def should_mirror_for_storage_mode(storage_mode: str | None) -> bool:
    return str(storage_mode or "").strip().lower() in CLOUD_MIRROR_STORAGE_MODES


def _artifact_label(artifact_kind: str | None) -> str:
    labels = {
        ARTIFACT_SINGLE_FILE: "Source file",
        ARTIFACT_BATCH_ZIP: "Batch ZIP",
        ARTIFACT_MSF: "MSF",
    }
    return labels.get(str(artifact_kind or "").strip(), "Uploaded artifact")


def _cloud_reference_from_upload_result(upload_result: dict[str, Any]) -> str | None:
    storage_provider = str(upload_result.get("storage_type") or "").strip().lower()
    if storage_provider == STORAGE_GDRIVE:
        return str(upload_result.get("file_id") or upload_result.get("remote_path") or "").strip() or None
    if storage_provider == STORAGE_DROPBOX:
        return str(upload_result.get("remote_path") or upload_result.get("file_id") or "").strip() or None
    return None


def _create_mirror_row(
    *,
    session_id: int,
    file_id: int | None,
    artifact_kind: str,
    original_filename: str,
    storage_provider: str | None,
    cloud_path: str | None,
    remote_url: str | None,
    status: str,
    error: str | None = None,
) -> CloudMirrorObject:
    row = CloudMirrorObject(
        session_id=int(session_id),
        file_id=int(file_id) if file_id is not None else None,
        artifact_kind=str(artifact_kind or ARTIFACT_SINGLE_FILE),
        original_filename=os.path.basename(str(original_filename or "").strip()) or "uploaded-artifact",
        storage_provider=str(storage_provider or "").strip().lower() or None,
        cloud_path=str(cloud_path or "").strip() or None,
        remote_url=str(remote_url or "").strip() or None,
        status=str(status or MIRROR_STATUS_PENDING).strip().lower(),
        error=str(error or "").strip() or None,
    )
    db.session.add(row)
    return row


def register_cloud_mirror_from_upload_result(
    *,
    session_id: int,
    file_id: int | None = None,
    artifact_kind: str,
    original_filename: str,
    upload_result: dict[str, Any],
) -> CloudMirrorObject:
    storage_provider = str(upload_result.get("storage_type") or "").strip().lower()
    cloud_path = _cloud_reference_from_upload_result(upload_result)
    success = bool(upload_result.get("success")) and storage_provider in CLOUD_STORAGE_PROVIDERS and bool(cloud_path)

    return _create_mirror_row(
        session_id=session_id,
        file_id=file_id,
        artifact_kind=artifact_kind,
        original_filename=original_filename,
        storage_provider=storage_provider if storage_provider in CLOUD_STORAGE_PROVIDERS else None,
        cloud_path=cloud_path,
        remote_url=upload_result.get("remote_url"),
        status=MIRROR_STATUS_AVAILABLE if success else MIRROR_STATUS_FAILED,
        error=None if success else str(upload_result.get("message") or "Cloud mirror upload failed."),
    )


def register_existing_cloud_reference(
    *,
    session_id: int,
    artifact_kind: str,
    original_filename: str,
    storage_provider: str,
    cloud_path: str,
    remote_url: str | None = None,
) -> CloudMirrorObject:
    return _create_mirror_row(
        session_id=session_id,
        file_id=None,
        artifact_kind=artifact_kind,
        original_filename=original_filename,
        storage_provider=storage_provider,
        cloud_path=cloud_path,
        remote_url=remote_url,
        status=MIRROR_STATUS_AVAILABLE,
    )


def mirror_local_artifact(
    *,
    session_id: int,
    local_path: str,
    original_filename: str | None = None,
    artifact_kind: str,
    file_id: int | None = None,
    storage_mode: str | None = None,
) -> CloudMirrorObject | None:
    if not should_mirror_for_storage_mode(storage_mode):
        return None

    filename = os.path.basename(str(original_filename or local_path or "").strip()) or "uploaded-artifact"
    if not local_path or not os.path.isfile(local_path):
        return _create_mirror_row(
            session_id=session_id,
            file_id=file_id,
            artifact_kind=artifact_kind,
            original_filename=filename,
            storage_provider=None,
            cloud_path=None,
            remote_url=None,
            status=MIRROR_STATUS_FAILED,
            error="Local artifact was not available for cloud mirroring.",
        )

    remote_name = f"session_{int(session_id)}_{artifact_kind}_{filename}"
    try:
        result = CloudUploadService.upload_file(local_path, remote_name)
    except Exception as exc:
        logger.error("Cloud mirror upload failed for session %s artifact %s: %s", session_id, filename, exc, exc_info=True)
        return _create_mirror_row(
            session_id=session_id,
            file_id=file_id,
            artifact_kind=artifact_kind,
            original_filename=filename,
            storage_provider=None,
            cloud_path=None,
            remote_url=None,
            status=MIRROR_STATUS_FAILED,
            error=str(exc),
        )

    return register_cloud_mirror_from_upload_result(
        session_id=session_id,
        file_id=file_id,
        artifact_kind=artifact_kind,
        original_filename=filename,
        upload_result=result,
    )


def unavailable_reason_for_storage_mode(storage_mode: str | None) -> str:
    normalized = str(storage_mode or "").strip().lower()
    if normalized == STORAGE_MODE_LOCAL:
        return "Cloud download is unavailable because this session was created in HPC/local storage mode."
    if normalized == STORAGE_MODE_SERVER_ONLY:
        return "Cloud download is unavailable because cloud mirroring is disabled for server-only storage."
    return "Cloud download is unavailable because this session does not have mirrored Cloud Storage artifacts."


def serialize_cloud_mirror_object(row: CloudMirrorObject, *, check_availability: bool = True) -> dict[str, Any]:
    payload = row.to_dict()
    payload["label"] = _artifact_label(row.artifact_kind)
    payload["can_download"] = False
    payload["availability_status"] = row.status
    payload["availability_message"] = row.error

    if row.status != MIRROR_STATUS_AVAILABLE:
        payload["availability_status"] = row.status or MIRROR_STATUS_FAILED
        payload["availability_message"] = row.error or "Cloud mirror is not available for this artifact."
        return payload

    if not row.storage_provider or not row.cloud_path:
        payload["availability_status"] = MIRROR_STATUS_FAILED
        payload["availability_message"] = row.error or "Cloud mirror metadata is incomplete."
        return payload

    if check_availability:
        available, message = CloudUploadService.check_cloud_object_available(row.cloud_path, row.storage_provider)
        row.checked_at = datetime.utcnow()
        payload["checked_at"] = row.checked_at.isoformat()
        payload["can_download"] = bool(available)
        payload["availability_status"] = MIRROR_STATUS_AVAILABLE if available else MIRROR_STATUS_FAILED
        payload["availability_message"] = message
        return payload

    payload["can_download"] = True
    payload["availability_message"] = "Cloud mirror metadata is available."
    return payload


def build_session_cloud_download_payload(
    session_row: DBSession,
    *,
    storage_mode: str | None = None,
    check_availability: bool = True,
) -> dict[str, Any]:
    rows = (
        CloudMirrorObject.query.filter_by(session_id=session_row.id)
        .order_by(CloudMirrorObject.created_at.asc(), CloudMirrorObject.id.asc())
        .all()
    )
    if not rows:
        return {
            "session_id": session_row.id,
            "available": False,
            "reason": unavailable_reason_for_storage_mode(storage_mode),
            "items": [],
        }

    items = [serialize_cloud_mirror_object(row, check_availability=check_availability) for row in rows]
    return {
        "session_id": session_row.id,
        "available": any(item.get("can_download") for item in items),
        "reason": None,
        "items": items,
    }
