import logging
import os
import shutil
import sqlite3
import json
from datetime import datetime

from flask import current_app

from database.database import db
from database.models import Session as DBSession
from exceptions import ValidationError
from services.audit_service import record_audit_event
from services.hdpc_schema_service import connect_hdpc, read_hdpc_provenance
from services.hdpc_shared_export_service import SHARED_EXPORT_ARTIFACT_KIND, read_shared_export_manifest

logger = logging.getLogger(__name__)


def _validate_hdpc_database(hdpc_path: str) -> dict:
    """Validate that the uploaded file is a readable .hdpc SQLite database."""
    conn = None
    try:
        conn = connect_hdpc(hdpc_path, readonly=True, timeout=10)
        cursor = conn.cursor()

        table_row = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='zenodo_records'"
        ).fetchone()
        if not table_row:
            raise ValidationError("Invalid .hdpc file: missing required table 'zenodo_records'")

        count_row = cursor.execute("SELECT COUNT(*) FROM zenodo_records").fetchone()
        record_count = int(count_row[0]) if count_row and count_row[0] is not None else 0
        shared_export_manifest = read_shared_export_manifest(hdpc_path)
        provenance = read_hdpc_provenance(hdpc_path)
        artifact_kind = (
            SHARED_EXPORT_ARTIFACT_KIND
            if isinstance(shared_export_manifest, dict)
            and str(shared_export_manifest.get("artifact_kind") or "").strip() == SHARED_EXPORT_ARTIFACT_KIND
            else "legacy_raw"
        )
        return {
            "record_count": record_count,
            "artifact_kind": artifact_kind,
            "shared_export_manifest": shared_export_manifest,
            "hdpc_provenance": provenance,
        }
    except sqlite3.DatabaseError as exc:
        raise ValidationError(f"Invalid .hdpc file: {exc}")
    finally:
        if conn:
            conn.close()


def import_hdpc_for_user(user_id: int, uploaded_file, *, actor_user_id: int | None = None) -> dict:
    """
    Import an uploaded .hdpc file and create a new session for the target user.
    """
    if uploaded_file is None:
        raise ValidationError("No file uploaded")

    original_filename = (uploaded_file.filename or "").strip()
    if not original_filename:
        raise ValidationError("No file selected")
    if not original_filename.lower().endswith(".hdpc"):
        raise ValidationError("Only .hdpc files are supported")

    session_manager = getattr(current_app, "session_manager", None)
    if not session_manager:
        raise ValidationError("Session manager is not configured")

    hdpc_path, _, _, session_dir = session_manager.create_session_dirs()

    try:
        uploaded_file.save(hdpc_path)

        validation = _validate_hdpc_database(hdpc_path)
        record_count = validation["record_count"]
        artifact_kind = str(validation.get("artifact_kind") or "legacy_raw").strip() or "legacy_raw"
        shared_export_manifest = (
            validation.get("shared_export_manifest")
            if isinstance(validation.get("shared_export_manifest"), dict)
            else None
        )
        hdpc_provenance = (
            validation.get("hdpc_provenance")
            if isinstance(validation.get("hdpc_provenance"), dict)
            else None
        )
        access_mode = "explorer_only" if artifact_kind == SHARED_EXPORT_ARTIFACT_KIND else "full"
        origin_metadata = {
            "artifact_kind": artifact_kind,
            "original_filename": original_filename,
        }
        if shared_export_manifest:
            origin_metadata["shared_export_manifest"] = shared_export_manifest
        if hdpc_provenance:
            origin_metadata["hdpc_provenance"] = hdpc_provenance

        db_session = DBSession(
            user_id=user_id,
            session_dir=session_dir,
            hdpc_path=hdpc_path,
            status="completed",
            sharing_scope="private",
            credential_preference="user",
            publishing_user_id=user_id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=False,
            origin_type="hdpc_import",
            access_mode=access_mode,
            origin_metadata_json=json.dumps(origin_metadata, sort_keys=True),
            timings="{}",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(db_session)
        db.session.flush()

        if artifact_kind == SHARED_EXPORT_ARTIFACT_KIND:
            record_audit_event(
                actor_user_id=actor_user_id or user_id,
                institution_id=None,
                session_id=db_session.id,
                event_type="hdpc_shared_export_imported",
                entity_type="session",
                entity_id=db_session.id,
                details={
                    "artifact_kind": artifact_kind,
                    "import_mode": access_mode,
                    "target_user_id": int(user_id),
                    "source_session_id": shared_export_manifest.get("source_session_id") if shared_export_manifest else None,
                    "source_institution_id": shared_export_manifest.get("source_institution_id")
                    if shared_export_manifest
                    else None,
                },
            )
        db.session.commit()

        logger.info(
            "Imported .hdpc for user %s into session %s (%s records)",
            user_id,
            db_session.id,
            record_count,
        )

        return {
            "session": {
                "id": db_session.id,
                "status": db_session.status,
                "origin_type": db_session.origin_type,
                "access_mode": db_session.access_mode,
                "created_at": db_session.created_at.isoformat() if db_session.created_at else None,
                "updated_at": db_session.updated_at.isoformat() if db_session.updated_at else None,
            },
            "import_summary": {
                "original_filename": original_filename,
                "record_count": record_count,
                "artifact_kind": artifact_kind,
            },
        }
    except ValidationError:
        db.session.rollback()
        if os.path.isdir(session_dir):
            shutil.rmtree(session_dir, ignore_errors=True)
        raise
    except Exception:
        db.session.rollback()
        if os.path.isdir(session_dir):
            shutil.rmtree(session_dir, ignore_errors=True)
        raise
