import io
import json
import os
import secrets
import shutil
import sqlite3
import tempfile

import pytest

pytest.importorskip("flask_jwt_extended")
pytest.importorskip("flask_sqlalchemy")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Institution, InstitutionMembership, InstitutionRole, Session as DBSession, User, UserRole
from middleware import setup_error_handlers
from routes.session_routes import session_bp
from services.hdpc_schema_service import HDPC_SCHEMA_VERSION, connect_hdpc, write_hdpc_provenance


class DummySessionManager:
    def __init__(self, base_path: str):
        self.base_path = base_path

    def create_session_dirs(self):
        session_dir = os.path.join(self.base_path, f"hdp_session_{secrets.token_hex(4)}")
        os.makedirs(session_dir, exist_ok=True)
        hdpc_path = os.path.join(session_dir, "session.hdpc")
        data_out_path = os.path.join(session_dir, "outputs")
        uploads_path = os.path.join(session_dir, "uploads")
        os.makedirs(data_out_path, exist_ok=True)
        os.makedirs(uploads_path, exist_ok=True)
        return hdpc_path, data_out_path, uploads_path, session_dir


def _build_source_hdpc(path: str) -> None:
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE project_info (
            project_id INTEGER PRIMARY KEY,
            project_name TEXT,
            project_short_code TEXT,
            description TEXT,
            creation_timestamp TEXT,
            last_modified_timestamp TEXT,
            hdpc_schema_version TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE project_configuration (
            config_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            config_key TEXT NOT NULL,
            config_value TEXT,
            description TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE file_scan_settings (
            scan_settings_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            modality TEXT NOT NULL,
            scan_options TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE source_files (
            file_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            absolute_path TEXT,
            relative_path TEXT,
            filename TEXT,
            size_bytes INTEGER,
            sha256_hash TEXT,
            mime_type TEXT,
            file_type TEXT,
            parent_file_id INTEGER,
            status TEXT,
            added_timestamp TEXT,
            last_processed_timestamp TEXT,
            error_message TEXT,
            is_primary_source INTEGER DEFAULT 0,
            pipeline_source TEXT,
            step_source TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE zenodo_records (
            record_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            source_file_id INTEGER,
            record_title TEXT,
            record_status TEXT,
            record_metadata_json TEXT,
            creation_api_response TEXT,
            last_publish_api_response TEXT,
            zenodo_record_id TEXT,
            concept_rec_id TEXT,
            zenodo_doi TEXT,
            concept_doi TEXT,
            is_sandbox INTEGER,
            created_timestamp TEXT,
            last_updated_timestamp TEXT,
            version TEXT,
            last_api_error TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE record_files_map (
            map_id INTEGER PRIMARY KEY,
            record_id INTEGER NOT NULL,
            file_id INTEGER NOT NULL,
            file_path TEXT,
            file_purpose TEXT,
            zenodo_file_id TEXT,
            zenodo_file_key TEXT,
            zenodo_file_checksum TEXT,
            zenodo_file_size INTEGER,
            zenodo_file_links_json TEXT,
            upload_status TEXT,
            upload_timestamp TEXT,
            upload_error TEXT,
            upload_response_json TEXT
        )
        """
    )
    cursor.execute("CREATE TABLE api_log (log_id INTEGER PRIMARY KEY, request_url TEXT)")
    cursor.execute("CREATE TABLE api_credentials (credential_id INTEGER PRIMARY KEY, api_key TEXT)")
    cursor.execute("CREATE TABLE metadata_backups (backup_id INTEGER PRIMARY KEY, payload_json TEXT)")

    absolute_path = "/Users/example/source/collections/model.glb"
    cursor.execute(
        """
        INSERT INTO project_info (
            project_id, project_name, project_short_code, description,
            creation_timestamp, last_modified_timestamp, hdpc_schema_version
        ) VALUES (1, 'Museum Project', 'MUSEUM', 'desc', '2026-03-30T00:00:00Z', '2026-03-30T00:00:00Z', 'webhdp-local-1')
        """
    )
    cursor.executemany(
        """
        INSERT INTO project_configuration (project_id, config_key, config_value, description)
        VALUES (?, ?, ?, ?)
        """,
        [
            (1, "preferences.zenodo_api_key", "prod-secret-token", "Prod token"),
            (1, "preferences.zenodo_sandbox_api_key", "sandbox-secret-token", "Sandbox token"),
            (1, "paths.data_in", "/Users/example/source", "Input directory"),
            (1, "main.use_sandbox", "true", "Sandbox"),
            (1, "core.use_sandbox", "true", "Sandbox"),
        ],
    )
    cursor.execute(
        """
        INSERT INTO file_scan_settings (project_id, modality, scan_options)
        VALUES (1, '3d', '{"recursive": true}')
        """
    )
    cursor.execute(
        """
        INSERT INTO source_files (
            file_id, project_id, absolute_path, relative_path, filename, size_bytes, sha256_hash,
            mime_type, file_type, status, added_timestamp, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            1,
            absolute_path,
            "collections/model.glb",
            "model.glb",
            1024,
            "abc123",
            "model/gltf-binary",
            "source",
            "uploaded",
            "2026-03-30T00:00:00Z",
            absolute_path,
        ),
    )
    cursor.execute(
        """
        INSERT INTO zenodo_records (
            record_id, project_id, source_file_id, record_title, record_status, record_metadata_json,
            creation_api_response, last_publish_api_response, zenodo_record_id, concept_rec_id,
            zenodo_doi, concept_doi, is_sandbox, created_timestamp, last_updated_timestamp, version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            1,
            1,
            "Museum Record",
            "draft",
            json.dumps({"metadata": {"title": "Museum Record"}, "links": {"html": "https://sandbox.zenodo.org/records/1001"}}),
            json.dumps({"local_path": absolute_path}),
            json.dumps({"latest_local_path": absolute_path}),
            "1001",
            "2001",
            "10.1234/museum.1",
            "10.1234/museum",
            1,
            "2026-03-30T00:00:00Z",
            "2026-03-30T00:00:00Z",
            "1.0.0",
        ),
    )
    cursor.execute(
        """
        INSERT INTO record_files_map (
            map_id, record_id, file_id, file_path, file_purpose, upload_status,
            upload_timestamp, upload_error, upload_response_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            1,
            1,
            absolute_path,
            "main",
            "uploaded",
            "2026-03-30T00:00:00Z",
            absolute_path,
            json.dumps({"local_file": absolute_path}),
        ),
    )
    cursor.execute("INSERT INTO api_log (log_id, request_url) VALUES (1, 'https://sandbox.zenodo.org/api/deposit/depositions')")
    cursor.execute("INSERT INTO api_credentials (credential_id, api_key) VALUES (1, 'secret')")
    cursor.execute("INSERT INTO metadata_backups (backup_id, payload_json) VALUES (1, '{\"title\": \"backup\"}')")
    conn.commit()
    conn.close()


@pytest.fixture()
def shared_export_app():
    temp_root = tempfile.mkdtemp(prefix="hdpc-shared-export-")
    shared_hdpc_path = os.path.join(temp_root, "shared-session.hdpc")
    personal_hdpc_path = os.path.join(temp_root, "personal-session.hdpc")
    _build_source_hdpc(shared_hdpc_path)
    shutil.copyfile(shared_hdpc_path, personal_hdpc_path)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "shared-export-secret"
    app.config["JWT_SECRET_KEY"] = "shared-export-jwt"

    db.init_app(app)
    JWTManager(app)
    setup_error_handlers(app)
    app.session_manager = DummySessionManager(temp_root)
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")

    with app.app_context():
        db.create_all()

        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        reader = User(email="reader@example.com", role=UserRole.USER, is_verified=True)
        reader.set_password("password123")
        outsider = User(email="outsider@example.com", role=UserRole.USER, is_verified=True)
        outsider.set_password("password123")
        moderator = User(email="moderator@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        db.session.add_all([owner, reader, outsider, moderator])
        db.session.flush()

        institution = Institution(name="Museum Network", slug="museum-network", created_by_user_id=owner.id)
        db.session.add(institution)
        db.session.flush()
        db.session.add_all(
            [
                InstitutionMembership(institution_id=institution.id, user_id=owner.id, role=InstitutionRole.OWNER),
                InstitutionMembership(institution_id=institution.id, user_id=reader.id, role=InstitutionRole.READER),
            ]
        )
        db.session.flush()

        shared_session = DBSession(
            user_id=owner.id,
            institution_id=institution.id,
            session_dir=temp_root,
            hdpc_path=shared_hdpc_path,
            status="completed",
            sharing_scope="institution",
            credential_preference="institution",
            publishing_user_id=owner.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=False,
            origin_type="workflow",
            access_mode="full",
        )
        personal_session = DBSession(
            user_id=owner.id,
            session_dir=os.path.join(temp_root, "personal"),
            hdpc_path=personal_hdpc_path,
            status="completed",
            sharing_scope="private",
            credential_preference="user",
            publishing_user_id=owner.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=False,
            origin_type="workflow",
            access_mode="full",
        )
        db.session.add_all([shared_session, personal_session])
        db.session.flush()

        provenance_conn = connect_hdpc(shared_hdpc_path)
        try:
            write_hdpc_provenance(
                provenance_conn,
                {
                    "creator_user_public_id": owner.public_id,
                    "creator_display_name": "Owner Curator",
                    "creator_profile_url": "https://webhdp.example/profiles/users/owner",
                    "institution_public_id": institution.public_id,
                    "institution_name": institution.name,
                    "institution_slug": institution.slug,
                    "institution_profile_url": "https://webhdp.example/profiles/institutions/museum-network",
                    "source_session_id": shared_session.id,
                },
            )
            provenance_conn.commit()
        finally:
            provenance_conn.close()

        db.session.commit()

        tokens = {
            "owner": create_access_token(identity=str(owner.id)),
            "reader": create_access_token(identity=str(reader.id)),
            "outsider": create_access_token(identity=str(outsider.id)),
            "moderator": create_access_token(identity=str(moderator.id)),
        }

        yield {
            "app": app,
            "client": app.test_client(),
            "temp_root": temp_root,
            "shared_session_id": shared_session.id,
            "personal_session_id": personal_session.id,
            "headers": {
                key: {"Authorization": f"Bearer {value}"}
                for key, value in tokens.items()
            },
        }

        db.session.remove()
        db.drop_all()
    shutil.rmtree(temp_root, ignore_errors=True)


def test_shared_export_route_sanitizes_content_and_permissions(shared_export_app):
    client = shared_export_app["client"]
    headers = shared_export_app["headers"]
    session_id = shared_export_app["shared_session_id"]
    personal_session_id = shared_export_app["personal_session_id"]

    raw_reader = client.get(f"/api/v1/sessions/{session_id}/hdpc", headers=headers["reader"])
    assert raw_reader.status_code == 404

    shared_reader = client.get(f"/api/v1/sessions/{session_id}/hdpc/shared", headers=headers["reader"])
    assert shared_reader.status_code == 200
    assert "session_" in shared_reader.headers.get("Content-Disposition", "")
    assert "_shared.hdpc" in shared_reader.headers.get("Content-Disposition", "")

    exported_path = os.path.join(shared_export_app["temp_root"], "reader-shared-export.hdpc")
    with open(exported_path, "wb") as handle:
        handle.write(shared_reader.data)

    conn = sqlite3.connect(exported_path)
    try:
        exported_tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert "api_log" not in exported_tables
        assert "api_credentials" not in exported_tables
        assert "metadata_backups" not in exported_tables

        config_keys = {
            row[0]
            for row in conn.execute("SELECT config_key FROM project_configuration").fetchall()
        }
        assert "preferences.zenodo_api_key" not in config_keys
        assert "preferences.zenodo_sandbox_api_key" not in config_keys
        assert {"main.use_sandbox", "core.use_sandbox", "shared_export.artifact_kind"}.issubset(config_keys)

        file_scan_count = conn.execute("SELECT COUNT(*) FROM file_scan_settings").fetchone()[0]
        assert file_scan_count == 0

        absolute_path, relative_path, error_message = conn.execute(
            "SELECT absolute_path, relative_path, error_message FROM source_files LIMIT 1"
        ).fetchone()
        assert absolute_path is None
        assert relative_path == "collections/model.glb"
        assert error_message is None

        file_path, upload_error, upload_response_json = conn.execute(
            "SELECT file_path, upload_error, upload_response_json FROM record_files_map LIMIT 1"
        ).fetchone()
        assert file_path == "collections/model.glb"
        assert upload_error is None
        assert json.loads(upload_response_json)["local_file"] == "collections/model.glb"

        manifest_row = conn.execute(
            """
            SELECT artifact_kind, format_version, import_mode, source_session_id,
                   source_owner_user_public_id, source_institution_public_id
            FROM shared_export_manifest
            LIMIT 1
            """
        ).fetchone()
        assert manifest_row[:4] == ("sanitized_shared", 1, "explorer_only", session_id)
        assert manifest_row[4]
        assert manifest_row[5]
        provenance_row = conn.execute(
            """
            SELECT creator_user_public_id, creator_display_name, institution_public_id, institution_slug, source_session_id
            FROM hdpc_provenance
            WHERE provenance_id = 1
            """
        ).fetchone()
        assert provenance_row[0] == manifest_row[4]
        assert provenance_row[1] == "Owner Curator"
        assert provenance_row[2] == manifest_row[5]
        assert provenance_row[3] == "museum-network"
        assert provenance_row[4] == session_id
        schema_row = conn.execute(
            "SELECT hdpc_schema_version FROM hdpc_schema_meta WHERE meta_id = 1"
        ).fetchone()
        assert schema_row == (HDPC_SCHEMA_VERSION,)
    finally:
        conn.close()

    outsider_shared = client.get(f"/api/v1/sessions/{session_id}/hdpc/shared", headers=headers["outsider"])
    assert outsider_shared.status_code == 404

    personal_shared = client.get(f"/api/v1/sessions/{personal_session_id}/hdpc/shared", headers=headers["owner"])
    assert personal_shared.status_code == 404


def test_imported_shared_export_creates_explorer_only_session(shared_export_app):
    client = shared_export_app["client"]
    headers = shared_export_app["headers"]
    session_id = shared_export_app["shared_session_id"]

    shared_export = client.get(f"/api/v1/sessions/{session_id}/hdpc/shared", headers=headers["reader"])
    assert shared_export.status_code == 200

    import_response = client.post(
        "/api/v1/sessions/import-hdpc",
        headers=headers["outsider"],
        data={"hdpc_file": (io.BytesIO(shared_export.data), "shared-export.hdpc")},
        content_type="multipart/form-data",
    )
    assert import_response.status_code == 201
    payload = import_response.get_json()["data"]
    imported_session_id = payload["session"]["id"]
    assert payload["import_summary"]["artifact_kind"] == "sanitized_shared"
    assert payload["session"]["origin_type"] == "hdpc_import"
    assert payload["session"]["access_mode"] == "explorer_only"

    with shared_export_app["app"].app_context():
        imported_session = db.session.get(DBSession, imported_session_id)
        assert imported_session is not None
        assert imported_session.institution_id is None
        assert imported_session.sharing_scope == "private"
        assert imported_session.origin_type == "hdpc_import"
        assert imported_session.access_mode == "explorer_only"
        assert imported_session.origin_metadata["artifact_kind"] == "sanitized_shared"

    records_response = client.get(
        f"/api/v1/sessions/{imported_session_id}/records",
        headers=headers["outsider"],
    )
    assert records_response.status_code == 200

    workflow_update = client.put(
        f"/api/v1/sessions/{imported_session_id}/workflow-state",
        headers=headers["outsider"],
        json={"phase": "metadata"},
    )
    assert workflow_update.status_code == 409
    assert workflow_update.get_json()["error"]["code"] == "SESSION_READ_ONLY"
