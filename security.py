import os
import re
import stat
import zipfile
from pathlib import Path
from werkzeug.utils import secure_filename

from exceptions import SecurityError, ValidationError


def path_is_within(base_path: str | Path, candidate_path: str | Path) -> bool:
    """Return True when candidate resolves under base."""
    try:
        base = Path(base_path).expanduser().resolve()
        candidate = Path(candidate_path).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return candidate == base or base in candidate.parents


def resolve_child_path(base_path: str | Path, user_path: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve a user-controlled child path under a trusted base directory."""
    text = str(user_path or "").strip()
    if not text:
        raise ValidationError("Path cannot be empty")

    base = Path(base_path).expanduser().resolve()
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base / text.lstrip("/\\")
    resolved = candidate.resolve(strict=False)

    if not path_is_within(base, resolved):
        raise SecurityError("Path is outside the allowed directory", details={"path": text})
    if must_exist and not resolved.exists():
        raise ValidationError("Path does not exist", details={"path": text})
    return resolved


def sanitize_upload_filename(filename: str, *, allowed_extensions: set[str] | None = None) -> str:
    """Sanitize an uploaded filename and optionally enforce an extension allowlist."""
    original = os.path.basename(str(filename or ""))
    safe = secure_filename(original)
    if not safe:
        raise ValidationError("Filename contains only invalid characters", details={"original_filename": original})

    if "/" in safe or "\\" in safe or safe in {".", ".."}:
        raise SecurityError("Invalid filename", details={"filename": original})

    if allowed_extensions is not None:
        file_ext = Path(safe).suffix.lower()
        if file_ext not in {ext.lower() for ext in allowed_extensions}:
            raise ValidationError(
                "File extension not allowed",
                details={"extension": file_ext, "allowed_extensions": sorted(allowed_extensions)},
            )
    return safe


def safe_extract_zip(zip_ref: zipfile.ZipFile, destination: str | Path, *, max_members: int = 10000) -> None:
    """Extract a ZIP archive after rejecting traversal, absolute paths, symlinks, and device entries."""
    dest = Path(destination).expanduser().resolve()
    members = zip_ref.infolist()
    if len(members) > max_members:
        raise ValidationError("ZIP archive contains too many entries", details={"max_members": max_members})

    for member in members:
        name = str(member.filename or "")
        normalized_name = name.replace("\\", "/")
        if not normalized_name or normalized_name.startswith("/") or normalized_name.startswith("../"):
            raise SecurityError("ZIP archive contains an unsafe path", details={"member": name})
        if "/../" in f"/{normalized_name}":
            raise SecurityError("ZIP archive contains an unsafe path", details={"member": name})

        mode = (member.external_attr >> 16) & 0o170000
        if mode in {stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK}:
            raise SecurityError("ZIP archive contains an unsafe file type", details={"member": name})

        target = (dest / normalized_name).resolve(strict=False)
        if not path_is_within(dest, target):
            raise SecurityError("ZIP archive member escapes destination", details={"member": name})

    zip_ref.extractall(dest)


class SecurityValidator:
    """Security validation utilities"""

    @staticmethod
    def validate_directory_path(directory_path, allowed_dirs=None):
        """
        Validates a directory path to prevent directory traversal attacks.
        """
        if not directory_path:
            raise ValidationError("Directory path cannot be empty")

        try:
            path = Path(directory_path).resolve()
        except (OSError, RuntimeError) as e:
            raise ValidationError(f"Invalid path", details={"error": str(e)})

        if not path.exists():
            raise ValidationError(f"Path does not exist", details={"path": directory_path})

        if not path.is_dir():
            raise ValidationError(f"Path is not a directory", details={"path": directory_path})

        # Prevent access to system directories
        forbidden_patterns = [
            r"^/etc",
            r"^/sys",
            r"^/proc",
            r"^/dev",
            r"^/boot",
            r"^/root",
            r"^C:\\Windows",
            r"^C:\\Program Files",
            r"^C:\\System",
        ]

        path_str = str(path)
        for pattern in forbidden_patterns:
            if re.match(pattern, path_str, re.IGNORECASE):
                raise SecurityError("Access to system directories is forbidden", details={"path": directory_path})

        if allowed_dirs:
            allowed = False
            for allowed_dir in allowed_dirs:
                try:
                    allowed_path = Path(allowed_dir).resolve()
                    if path == allowed_path or allowed_path in path.parents:
                        allowed = True
                        break
                except (OSError, RuntimeError):
                    continue

            if not allowed:
                raise SecurityError("Directory not in allowed list", details={"path": directory_path})

        return str(path)

    @staticmethod
    def validate_filename(filename, allowed_extensions):
        """Validates and sanitizes a filename."""
        if not filename:
            raise ValidationError("Filename cannot be empty")

        filename = os.path.basename(filename)
        safe_filename = sanitize_upload_filename(filename)

        if not safe_filename:
            raise ValidationError("Filename contains only invalid characters", details={"original_filename": filename})

        file_ext = Path(safe_filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise ValidationError(
                f"File extension not allowed",
                details={"extension": file_ext, "allowed_extensions": list(allowed_extensions)},
            )

        if safe_filename.count(".") > 1:
            parts = safe_filename.split(".")
            for i in range(1, len(parts)):
                ext = "." + parts[i].lower()
                if ext not in allowed_extensions and ext not in {".tar", ".gz", ".bz2"}:
                    raise SecurityError("Multiple extensions detected", details={"filename": safe_filename})

        return safe_filename

    @staticmethod
    def validate_file_size(file_size, max_size):
        """Validates file size is within allowed limits."""
        if file_size > max_size:
            max_mb = max_size / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            raise ValidationError(
                f"File too large", details={"file_size_mb": round(actual_mb, 2), "max_size_mb": round(max_mb, 2)}
            )
