"""Direct uploads shared by the application and isolated workflow tests."""
import json
import os
from flask import Blueprint, current_app, request, session
from flask_jwt_extended import get_jwt_identity, jwt_required
from api_utils import APIResponse
from database.models import UserMetadata
from exceptions import AppException, FileProcessingError, SecurityError
from security import SecurityValidator, sanitize_upload_filename
from services.hdpc_provenance_service import build_hdpc_provenance
from services.single_upload_recovery import single_upload_request

app = current_app
security_validator = SecurityValidator()
single_file_bp = Blueprint('single_file', __name__)

SINGLE_FILE_ALLOWED_EXTENSIONS = {
    ".obj",
    ".mtl",
    ".glb",
    ".gltf",
    ".bin",
    ".ply",
    ".stl",
    ".fbx",
    ".dae",
    ".usdz",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".xml",
    ".txt",
}


def _create_session_dirs(
    *,
    institution_id=None,
    sharing_scope=None,
    credential_preference=None,
    publishing_user_id=None,
    default_zenodo_environment=None,
    use_institution_default_communities=None,
):
    """
    Creates temporary directories for a user session and saves to database.
    Returns:
        tuple: (hdpc_path, data_out_path, uploads_path)
    """
    from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

    from database.database import db
    from database.models import Session as DBSession

    # Verify JWT in request
    try:
        verify_jwt_in_request()
        user_id_str = get_jwt_identity()
        user_id = int(user_id_str)  # Convert back to integer
    except Exception as e:
        app.logger.error(f"JWT verification failed: {e}")
        raise SecurityError("Authentication required")

    hdpc_path, data_out_path, uploads_path, session_dir = current_app.session_manager.create_session_dirs()

    # Create database session record
    db_session = DBSession(
        user_id=user_id,
        institution_id=institution_id,
        session_dir=session_dir,
        hdpc_path=hdpc_path,
        status="queued",
        sharing_scope=sharing_scope or ("institution" if institution_id else "private"),
        credential_preference=credential_preference or ("institution" if institution_id else "user"),
        publishing_user_id=publishing_user_id or user_id,
        default_zenodo_environment=default_zenodo_environment or "sandbox",
        use_institution_default_communities=bool(use_institution_default_communities) if institution_id else False,
        origin_type="workflow",
        access_mode="full",
    )
    db.session.add(db_session)
    from services.single_upload_recovery import persist_single_upload_identity
    persist_single_upload_identity(db_session)
    from services.directory_upload_recovery import persist_directory_upload_identity
    persist_directory_upload_identity(db_session)
    db.session.commit()

    # Store in Flask session
    session["hdpc_path"] = hdpc_path
    session["session_dir"] = session_dir
    session["data_out_path"] = data_out_path
    session["uploads_path"] = uploads_path
    session["db_session_id"] = db_session.id
    session.permanent = True

    app.logger.info(f"Session directories created at {session_dir}, DB session ID: {db_session.id}")
    return hdpc_path, data_out_path, uploads_path


@single_file_bp.route("/file", methods=["POST"])
@jwt_required()
@single_upload_request(SINGLE_FILE_ALLOWED_EXTENSIONS)
def api_start_session_file():
    """
    API endpoint for file upload (Vue frontend compatible)
    """
    from pathlib import Path

    from database.database import db
    from database.models import File as DBFile
    from database.models import Session as DBSession, User
    from routes.session_routes import _normalize_session_workspace_options
    from routes.access_helpers import get_current_user_from_jwt

    app.logger.info("Handling single file upload request via API.")

    db_session_id = None
    try:
        if "file" not in request.files:
            app.logger.error("No file in request.files")
            return APIResponse.error("No file provided", 422)

        file = request.files["file"]

        if not file or file.filename == "":
            app.logger.error("Empty filename")
            return APIResponse.error("No file selected", 422)

        # Step 1: Create session directories and get paths
        workspace_payload = {
            key: request.form.get(key)
            for key in (
                "institution_id",
                "sharing_scope",
                "credential_preference",
                "default_zenodo_environment",
                "use_institution_default_communities",
            )
            if request.form.get(key) is not None
        }
        current_user = get_current_user_from_jwt() or db.session.get(User, int(get_jwt_identity()))
        workspace_options = _normalize_session_workspace_options(user=current_user, payload=workspace_payload)
        hdpc_path, data_out_path, uploads_path = _create_session_dirs(
            institution_id=workspace_options["institution_id"],
            sharing_scope=workspace_options["sharing_scope"],
            credential_preference=workspace_options["credential_preference"],
            publishing_user_id=workspace_options["publishing_user_id"],
            default_zenodo_environment=workspace_options["default_zenodo_environment"],
            use_institution_default_communities=workspace_options["use_institution_default_communities"],
        )
        db_session_id = session.get("db_session_id")  # <-- Get session ID
        if not db_session_id:
            app.logger.error("Failed to create a database session ID.")
            return APIResponse.error("SESSION_CREATION_FAILED", "Could not create session", 500)

        # Step 2: Save the uploaded file to the session's 'uploads' directory
        safe_filename = sanitize_upload_filename(file.filename, allowed_extensions=SINGLE_FILE_ALLOWED_EXTENSIONS)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        security_validator.validate_file_size(file_size, app.config["MAX_CONTENT_LENGTH"])
        saved_file_path = os.path.join(uploads_path, safe_filename)
        file.save(saved_file_path)
        app.logger.info(f"File saved to: {saved_file_path}")

        # Step 3: Save file metadata to our web app's database
        db_file = DBFile(
            session_id=db_session_id,
            filename=safe_filename,
            path=saved_file_path,
            size=os.path.getsize(saved_file_path),
            status="uploaded",
        )
        db.session.add(db_file)
        db.session.commit()

        try:
            from constants import UPLOAD_STORAGE_MODE_FIELD
            from services.cloud_mirror_service import ARTIFACT_SINGLE_FILE, mirror_local_artifact
            from services.cloud_upload_service import CloudUploadService

            storage_mode = CloudUploadService.get_storage_mode()
            db.session.add(
                UserMetadata(
                    session_id=db_session_id,
                    field_name=UPLOAD_STORAGE_MODE_FIELD,
                    field_value=str(storage_mode),
                )
            )
            mirror_local_artifact(
                session_id=db_session_id,
                local_path=saved_file_path,
                original_filename=safe_filename,
                artifact_kind=ARTIFACT_SINGLE_FILE,
                file_id=db_file.id,
                storage_mode=storage_mode,
            )
            db.session.commit()
        except Exception as mirror_exc:
            db.session.rollback()
            app.logger.warning("Failed to persist Cloud Storage mirror metadata for session %s: %s", db_session_id, mirror_exc)

        # Get the file extension (e.g., '.glb')
        file_ext = Path(safe_filename).suffix.lower()
        if not file_ext:
            app.logger.error(f"File '{safe_filename}' has no extension, cannot determine scan options.")
            raise FileProcessingError("File has no extension, cannot determine scan options.")

        # Create a mutable set of extensions from the config
        extensions_set = set(app.config["ALLOWED_EXTENSIONS"])

        # Add the uploaded file's extension to the set
        extensions_set.add(file_ext)

        # Convert back to list for JSON serialization
        final_extensions_list = list(extensions_set)

        # Create scan options specifically for this single file
        single_file_scan_options = {
            "extensions": final_extensions_list,  # <-- Use the new list
            "primarysourceext": file_ext,  # Treat this file's extension as the primary
            "bundling": {"enabled": False},  # Disable bundling
            "obj_options": {"add_mtl": False, "add_textures": False, "archive_subdirectories": False},
        }

        app.logger.info(f"Using single-file scan options with primary extension: {file_ext}")
        app.logger.info(f"Full extension list for scanner: {final_extensions_list}")

        # Step 4: Call create_and_scan on the 'uploads_path'
        db_session = db.session.get(DBSession, db_session_id)
        scan_data = current_app.project_service.create_and_scan(
            hdpc_path=hdpc_path,
            data_in_path=uploads_path,  # Use the uploads directory as the input
            data_out_path=data_out_path,
            project_name="HDP Web Session (File)",
            scan_options=single_file_scan_options,  # Use the new options
            provenance=build_hdpc_provenance(
                user=current_user,
                session=db_session,
                institution=workspace_options.get("institution"),
            ),
        )
        app.logger.info(f"Scan completed. Found {scan_data.get('filesAdded', 0)} files.")

        # Step 5: The local scan/bootstrap path now writes the .hdpc directly.
        app.logger.info(f"Prepared local project context at {hdpc_path} for file session.")

        # --- Update session status to "active" on success ---
        try:
            if db_session:
                db_session.status = "scanned"
                from flask import g
                if getattr(g, 'single_upload_identity', None):
                    from services.single_upload_recovery import RESULT_FIELD
                    db.session.add(UserMetadata(session_id=db_session_id, field_name=RESULT_FIELD,
                        field_value=json.dumps({'foundFiles': scan_data.get('foundFiles', []), 'session_id': db_session_id, 'file_id': db_file.id})))
                db.session.commit()
        except Exception as e_inner:
            app.logger.error(f"Failed to update session {db_session_id} status to scanned: {e_inner}")
            # Don't fail the whole request, but log it

        # Step 6: Return the *actual* file list from the scan
        return APIResponse.success(
            data={
                "foundFiles": scan_data.get("foundFiles", []),  # Return real scan data
                "session_id": db_session_id,
                "file_id": db_file.id,
            },
            message="File uploaded and scanned successfully",
        )

    except Exception as e:
        app.logger.error(f"File upload error: {e}", exc_info=True)

        # --- Update session status to "failed" on error ---
        if db_session_id:
            try:
                db_session = db.session.get(DBSession, db_session_id)
                if db_session:
                    db_session.status = "failed"
                    db.session.commit()
                    app.logger.info(f"Set session {db_session_id} status to 'failed'")
            except Exception as e_inner:
                app.logger.error(f"Failed to update session {db_session_id} status to failed: {e_inner}")

        # Re-raise user-facing exceptions to let global handler process them
        if isinstance(e, AppException):
            raise e

        # Wrap unexpected exceptions in AppException or just raise to let generic 500 handler catch it
        raise e
