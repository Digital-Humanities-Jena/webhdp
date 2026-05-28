from flask import Blueprint, request, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required
from api_utils import APIResponse
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_PURE_CLOUD
from database.database import db
from database.models import User
import logging
import os
from security import sanitize_upload_filename

upload_bp = Blueprint("upload", __name__)
logger = logging.getLogger(__name__)

@upload_bp.route("/stream", methods=["POST"])
@jwt_required()
def stream_upload():
    """
    Stream a file upload directly to cloud storage.
    Expects raw body stream or chunked transfer encoding.
    Headers:
        X-File-Name: Original filename
        Content-Length: Total file size (optional but recommended)
    """
    try:
        raw_filename = request.headers.get("X-File-Name")
        if not raw_filename:
            return APIResponse.validation_error("Missing X-File-Name header")
        filename = sanitize_upload_filename(raw_filename)

        content_length = request.headers.get("Content-Length")
        try:
            file_size = int(content_length) if content_length else 0
        except (TypeError, ValueError):
            return APIResponse.validation_error("Content-Length must be an integer")
        max_size = int(current_app.config.get("MAX_CONTENT_LENGTH") or 100 * 1024 * 1024)
        if file_size <= 0:
            return APIResponse.validation_error("Content-Length is required for streaming uploads")
        if file_size > max_size:
            return APIResponse.error(
                "FILE_TOO_LARGE",
                "Uploaded file exceeds maximum allowed size",
                413,
                details={"max_size_mb": max_size / (1024 * 1024)},
            )

        logger.info(f"Starting stream upload for: {filename} (Size: {file_size})")

        # Get storage mode
        mode = CloudUploadService.get_storage_mode()

        # We only support direct streaming for pure_cloud mode currently
        # For other modes, we could implement fallback, but for now enforcing consistency

        result = CloudUploadService.stream_upload_file(
            request.stream,
            filename,
            file_size
        )

        if result.get("success"):
            allocation_id = str(request.headers.get("X-HPC-Allocation-ID") or "").strip()
            if allocation_id and hasattr(current_app, "hpc_allocation_service"):
                try:
                    user = db.session.get(User, int(get_jwt_identity()))
                    if user is None:
                        return APIResponse.not_found("User not found")
                    cloud_path = result.get("remote_path") or result.get("file_id")
                    if not cloud_path:
                        return APIResponse.error(
                            "HPC_STAGING_FAILED",
                            "Cloud upload succeeded, but no cloud object reference was returned for HPC staging.",
                            502,
                            details=result,
                        )
                    allocation = current_app.hpc_allocation_service.get_allocation(allocation_id, user)
                    result["hpc_staging"] = current_app.hpc_allocation_service.stage_cloud_references(
                        allocation,
                        [
                            {
                                "cloud_path": cloud_path,
                                "storage_type": result.get("storage_type"),
                                "name": filename,
                                "relative_dir": sanitize_upload_filename(request.headers.get("X-HPC-Relative-Dir") or "uploads"),
                            }
                        ],
                    )
                except Exception as staging_exc:
                    logger.error("HPC staging after stream upload failed: %s", staging_exc, exc_info=True)
                    return APIResponse.error(
                        "HPC_STAGING_FAILED",
                        f"File uploaded to cloud, but HPC staging failed: {staging_exc}",
                        502,
                        details={"upload": result},
                    )
            return APIResponse.success(
                data=result,
                message="File streamed successfully to cloud storage"
            )
        else:
            return APIResponse.error(
                "STREAM_UPLOAD_FAILED",
                message=f"Stream upload failed: {result.get('message')}",
                status_code=500,
                details=result
            )

    except Exception as e:
        logger.error(f"Stream upload error: {e}", exc_info=True)
        return APIResponse.server_error(f"Stream upload failed: {str(e)}")
