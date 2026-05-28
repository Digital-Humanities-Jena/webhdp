import os

import pandas as pd
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Session as DBSession, User, UserRole
from routes.msf_routes import msf_bp
from routes.tools_routes import tools_bp
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL
from services.msf_service import MSFService
from services.user_service import UserService


class _DummyProjectService:
    def _translate_path(self, path, to_container=True):
        return path


def _write_csv(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def test_patch_msf_dry_run_reports_duplicate_blocker(tmp_path):
    msf_path = tmp_path / "input.csv"
    _write_csv(
        str(msf_path),
        "filename,title\n"
        "/asset.glb,First\n"
        "asset.glb,Second\n"
        "other.obj,Other\n",
    )

    service = MSFService()
    report = service.patch_msf_file(
        file_path=str(msf_path),
        parse_options={"delimiter": ",", "use_first_row_as_header": True},
        duplicate_policy="fail",
        apply=False,
    )

    assert report["is_valid"] is False
    assert report["patched_msf_path"] is None
    assert report["summary"]["filename_cells_normalized"] >= 1
    assert any("Duplicate filenames remain" in item for item in report["blockers"])


def test_patch_msf_keep_first_writes_patched_file_and_validates(tmp_path):
    (tmp_path / "asset.glb").write_bytes(b"glb")
    (tmp_path / "other.obj").write_bytes(b"obj")

    msf_path = tmp_path / "input.csv"
    _write_csv(
        str(msf_path),
        "filename,title,description\n"
        "/asset.glb,First,\n"
        "asset.glb,Second,From duplicate\n"
        "other.obj,Other,Description\n",
    )

    service = MSFService()
    report = service.patch_msf_file(
        file_path=str(msf_path),
        parse_options={"delimiter": ",", "use_first_row_as_header": True},
        directory_files=["asset.glb", "other.obj"],
        directory_root=str(tmp_path),
        duplicate_policy="keep_first",
        apply=True,
        output_dir=str(tmp_path),
    )

    assert report["is_valid"] is True
    assert report["patched_msf_path"]
    assert os.path.exists(report["patched_msf_path"])
    assert report["summary"]["duplicate_rows_removed"] == 1
    assert report["validation"]["matched_count"] == 2

    patched_df = pd.read_csv(report["patched_msf_path"], dtype=str, delimiter=",").fillna("")
    assert len(patched_df) == 2
    assert patched_df["filename"].tolist() == ["asset.glb", "other.obj"]
    assert patched_df.iloc[0]["title"] == "First"


def test_patch_msf_merge_non_empty_combines_duplicate_row_values(tmp_path):
    msf_path = tmp_path / "input.csv"
    _write_csv(
        str(msf_path),
        "filename,title,description\n"
        "/asset.glb,First,\n"
        "asset.glb,,From duplicate\n",
    )

    service = MSFService()
    report = service.patch_msf_file(
        file_path=str(msf_path),
        parse_options={"delimiter": ",", "use_first_row_as_header": True},
        duplicate_policy="merge_non_empty",
        apply=True,
        output_dir=str(tmp_path),
    )

    assert report["is_valid"] is True
    assert report["summary"]["duplicate_rows_merged"] == 1
    patched_df = pd.read_csv(report["patched_msf_path"], dtype=str, delimiter=",").fillna("")
    assert len(patched_df) == 1
    assert patched_df.iloc[0]["filename"] == "asset.glb"
    assert patched_df.iloc[0]["title"] == "First"
    assert patched_df.iloc[0]["description"] == "From duplicate"


def test_patch_route_returns_report_for_authenticated_request(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    JWTManager(app)
    app.project_service = _DummyProjectService()
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")

    with app.app_context():
        token = create_access_token(identity="1")

    msf_path = tmp_path / "input.csv"
    _write_csv(
        str(msf_path),
        "filename,title\n"
        "/asset.glb,First\n"
        "asset.glb,Second\n",
    )
    (tmp_path / "asset.glb").write_bytes(b"glb")

    client = app.test_client()
    response = client.post(
        "/api/v1/msf/patch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msf_path": str(msf_path),
            "directory_path": str(tmp_path),
            "duplicate_policy": "keep_first",
            "parse_options": {"delimiter": ",", "use_first_row_as_header": True},
            "apply": False,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["is_valid"] is True
    assert payload["data"]["summary"]["duplicate_rows_removed"] == 1
    assert payload["data"]["validation"]["matched_count"] == 1


def test_patch_route_resolves_relative_directory_in_local_mode(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path / "local_input")
    JWTManager(app)
    app.project_service = _DummyProjectService()
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")

    monkeypatch.setattr(CloudUploadService, "get_storage_mode", lambda: STORAGE_MODE_LOCAL)

    with app.app_context():
        token = create_access_token(identity="1")

    local_root = tmp_path / "local_input"
    target_dir = local_root / "rcin"
    target_dir.mkdir(parents=True)
    (target_dir / "asset.glb").write_bytes(b"glb")

    msf_path = local_root / "rcin_dataset.csv"
    _write_csv(
        str(msf_path),
        "filename,title\n"
        "asset.glb,Artifact\n",
    )

    client = app.test_client()
    response = client.post(
        "/api/v1/msf/patch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msf_path": str(msf_path),
            "directory_path": "rcin",
            "duplicate_policy": "merge_non_empty",
            "parse_options": {"delimiter": ",", "use_first_row_as_header": True},
            "apply": False,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["is_valid"] is True
    assert payload["data"]["validation"]["matched_count"] == 1


def test_patch_msf_auto_recovers_headerless_csv_without_parse_options(tmp_path):
    msf_path = tmp_path / "headerless.csv"
    _write_csv(
        str(msf_path),
        "asset_a.glb,Title A,Desc A\n"
        "asset_b.glb,Title B,Desc B\n",
    )

    service = MSFService()
    report = service.patch_msf_file(
        file_path=str(msf_path),
        parse_options=None,
        directory_files=["asset_a.glb", "asset_b.glb"],
        duplicate_policy="merge_non_empty",
        apply=False,
    )

    assert report["is_valid"] is True
    assert report["filename_column"] == "filename"
    assert report["validation"]["matched_count"] == 2
    assert report["summary"]["filename_like_rows"] == 2


def test_patch_msf_removes_embedded_headers_and_repairs_references(tmp_path):
    msf_path = tmp_path / "hunt_like.csv"
    _write_csv(
        str(msf_path),
        "model_one.glb,Title One\n"
        "filename,title\n"
        "model-two.glb,Title Two\n"
        "spirit_barrell.jpg,Spirit Barrel\n",
    )

    service = MSFService()
    report = service.patch_msf_file(
        file_path=str(msf_path),
        parse_options={"delimiter": ",", "use_first_row_as_header": False},
        directory_files=["model_one.glb", "model_two.glb", "spirit_barrel.glb"],
        directory_root=str(tmp_path),
        duplicate_policy="merge_non_empty",
        apply=True,
        output_dir=str(tmp_path),
    )

    assert report["is_valid"] is True
    assert report["summary"]["embedded_header_rows_removed"] == 1
    assert report["summary"]["filename_references_repaired"] == 2
    assert report["validation"]["matched_count"] == 3

    patched_df = pd.read_csv(report["patched_msf_path"], dtype=str, delimiter=",").fillna("")
    assert patched_df["filename"].tolist() == [
        "model_one.glb",
        "model_two.glb",
        "spirit_barrel.glb",
    ]


def test_run_local_validator_reference_repair_enforces_unique_matches(tmp_path):
    msf_path = tmp_path / "conflicts.csv"
    _write_csv(
        str(msf_path),
        "filename,title\n"
        "flint_dagger.glb,Primary\n"
        "flint_dagger_HCA065.glb,Secondary\n",
    )

    service = MSFService()
    report = service.run_local_validator(
        file_path=str(msf_path),
        parse_options={"delimiter": ",", "use_first_row_as_header": True},
        directory_files=["flint_dagger (1).glb"],
        directory_root=str(tmp_path),
        duplicate_scan_columns=["filename"],
        operations=[
            {
                "type": "repair_references",
                "column": "filename",
                "match_by_stem": True,
                "fuzzy_match": True,
                "enforce_unique_matches": True,
                "keep_unresolved": True,
            }
        ],
        include_reference_check=False,
        include_dataframe=True,
    )

    assert report["is_valid"] is True
    transformed_df = report["_dataframe"]
    assert transformed_df.iloc[0]["filename"] == "flint_dagger (1).glb"
    assert transformed_df.iloc[1]["filename"] == "flint_dagger_HCA065.glb"
    op_report = report["operations"][0]
    assert op_report["changed_cells"] == 1
    assert op_report["unresolved_count"] == 1


def test_run_local_validator_supports_duplicate_resolution_and_column_merge(tmp_path):
    msf_path = tmp_path / "input.csv"
    _write_csv(
        str(msf_path),
        "filename,title\n"
        "asset.glb,Artifact\n"
        "asset.glb,Artifact\n"
        "other.glb,Other\n",
    )

    service = MSFService()
    report = service.run_local_validator(
        file_path=str(msf_path),
        parse_options={"delimiter": ",", "use_first_row_as_header": True},
        directory_files=["asset.glb", "other.glb"],
        directory_root=str(tmp_path),
        duplicate_scan_columns=["title", "filename"],
        operations=[
            {
                "type": "resolve_duplicates",
                "columns": ["title"],
                "strategy": "suffix_with_filename",
                "target_column": "title",
                "filename_column": "filename",
                "delimiter": "—",
                "auto_space": True,
            },
            {
                "type": "merge_columns",
                "source_columns": ["title", "filename"],
                "target_column": "title",
                "delimiter": "/",
                "auto_space": True,
                "overwrite": True,
            },
        ],
        include_reference_check=False,
        include_dataframe=True,
    )

    assert report["is_valid"] is True
    assert report["summary"]["operations_applied"] == 2
    transformed_df = report["_dataframe"]
    assert transformed_df.iloc[0]["title"] == "Artifact / asset.glb"
    assert transformed_df.iloc[1]["title"] == "Artifact — asset.glb / asset.glb"


def test_local_validator_routes_require_admin_and_local_mode_and_export(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    JWTManager(app)
    app.project_service = _DummyProjectService()
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")

    class _DummyUser:
        role = UserRole.ADMIN

    monkeypatch.setattr(UserService, "get_by_id", lambda self, _user_id: _DummyUser())
    monkeypatch.setattr(CloudUploadService, "get_storage_mode", lambda: STORAGE_MODE_LOCAL)

    with app.app_context():
        token = create_access_token(identity="1")

    msf_path = tmp_path / "input.csv"
    _write_csv(
        str(msf_path),
        "filename,title\n"
        "asset.glb,Artifact\n",
    )
    (tmp_path / "asset.glb").write_bytes(b"glb")

    client = app.test_client()
    validate_response = client.post(
        "/api/v1/msf/tools/local/validate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msf_path": str(msf_path),
            "directory_path": "",
            "duplicate_scan_columns": ["filename"],
            "operations": [{"type": "trim_whitespace"}],
            "recursive": False,
        },
    )
    assert validate_response.status_code == 200
    validate_payload = validate_response.get_json()
    assert validate_payload["success"] is True
    assert validate_payload["data"]["is_valid"] is True
    assert validate_payload["data"]["checks"]["reference_availability"]["matched_count"] == 1

    export_response = client.post(
        "/api/v1/msf/tools/local/export",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msf_path": str(msf_path),
            "directory_path": "",
            "format": "csv",
            "duplicate_scan_columns": ["filename"],
            "operations": [],
            "recursive": False,
        },
    )
    assert export_response.status_code == 200
    assert export_response.headers["Content-Type"].startswith("text/csv")
    assert "attachment;" in export_response.headers.get("Content-Disposition", "")
    assert b"filename" in export_response.data
    assert b"title" in export_response.data


def test_run_local_validator_reference_repair_and_text_normalize(tmp_path):
    msf_path = tmp_path / "input.csv"
    _write_csv(
        str(msf_path),
        "filename,title\n"
        "nested/path/asset.glb,artifact one; Artifact One;artifact one\n"
        "other.glb,second title\n",
    )

    service = MSFService()
    report = service.run_local_validator(
        file_path=str(msf_path),
        parse_options={"delimiter": ",", "use_first_row_as_header": True},
        directory_files=["asset.glb", "other.glb"],
        directory_root=str(tmp_path),
        duplicate_scan_columns=["filename"],
        operations=[
            {
                "type": "repair_references",
                "column": "filename",
                "match_by_stem": True,
                "keep_unresolved": True,
            },
            {
                "type": "normalize_text_columns",
                "columns": ["title"],
                "mode": "title",
                "collapse_whitespace": True,
                "dedupe_delimited": True,
                "delimiter": ";",
                "auto_space": True,
            },
        ],
        include_reference_check=True,
        include_dataframe=True,
    )

    assert report["is_valid"] is True
    assert report["summary"]["operations_applied"] == 2
    transformed_df = report["_dataframe"]
    assert transformed_df.iloc[0]["filename"] == "asset.glb"
    assert transformed_df.iloc[0]["title"] == "Artifact One"


def test_tools_routes_context_preflight_and_metadata_normalizer(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    JWTManager(app)
    db.init_app(app)
    app.project_service = _DummyProjectService()
    app.msf_service = MSFService()

    class _DummySvc:
        def __init__(self, url):
            self.service_url = url

        def check_health(self):
            return True

    app.fast_renderer_service = _DummySvc("http://fast-renderer:5002")
    app.any_to_usdz_service = _DummySvc("http://any-to-usdz:5003")
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")

    class _DummyUser:
        role = UserRole.ADMIN

    monkeypatch.setattr(UserService, "get_by_id", lambda self, _user_id: _DummyUser())
    monkeypatch.setattr(CloudUploadService, "get_storage_mode", lambda: STORAGE_MODE_LOCAL)

    with app.app_context():
        db.create_all()
        admin_user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin_user.set_password("password123")
        db.session.add(admin_user)
        db.session.commit()
        db.session.add_all(
            [
                DBSession(user_id=admin_user.id, session_dir=str(tmp_path / "s_active"), status="active"),
                DBSession(user_id=admin_user.id, session_dir=str(tmp_path / "s_processing"), status="processing"),
                DBSession(user_id=admin_user.id, session_dir=str(tmp_path / "s_ready"), status="ready"),
                DBSession(user_id=admin_user.id, session_dir=str(tmp_path / "s_completed"), status="completed"),
                DBSession(user_id=admin_user.id, session_dir=str(tmp_path / "s_failed"), status="failed"),
            ]
        )
        db.session.commit()
        token = create_access_token(identity=str(admin_user.id))

    msf_path = tmp_path / "input.csv"
    _write_csv(
        str(msf_path),
        "filename,title\n"
        "asset.glb,artifact one;artifact one\n",
    )
    (tmp_path / "asset.glb").write_bytes(b"glb")

    client = app.test_client()
    context_response = client.get(
        "/api/v1/tools/context",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert context_response.status_code == 200
    context_payload = context_response.get_json()
    assert context_payload["success"] is True
    assert context_payload["data"]["features"]["pipeline_preflight"]["enabled"] is True
    assert context_payload["data"]["features"]["native_playground"]["enabled"] is True
    assert context_payload["data"]["pipeline_platform"]["official_platform_id"] == "webhdp_native_pipeline_platform"

    preflight_response = client.post(
        "/api/v1/tools/pipeline-preflight/local",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msf_path": str(msf_path),
            "directory_path": "",
            "duplicate_scan_columns": ["filename"],
            "recursive": False,
        },
    )
    assert preflight_response.status_code == 200
    preflight_payload = preflight_response.get_json()
    assert preflight_payload["success"] is True
    assert preflight_payload["data"]["validator"]["is_valid"] is True

    normalize_response = client.post(
        "/api/v1/tools/metadata-normalizer/local",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msf_path": str(msf_path),
            "columns": ["title"],
            "mode": "title",
            "dedupe_delimited": True,
            "delimiter": ";",
            "recursive": False,
        },
    )
    assert normalize_response.status_code == 200
    normalize_payload = normalize_response.get_json()
    assert normalize_payload["success"] is True
    assert normalize_payload["data"]["summary"]["operations_applied"] == 1

    diagnostics_response = client.get(
        "/api/v1/tools/hpc-diagnostics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert diagnostics_response.status_code == 200
    diagnostics_payload = diagnostics_response.get_json()
    assert diagnostics_payload["success"] is True
    assert {
        "backend",
        "fast_renderer",
        "any_to_usdz",
        "redis",
    }.issubset(diagnostics_payload["data"]["services"].keys())
    assert diagnostics_payload["data"]["sessions"]["total"] == 5
    assert diagnostics_payload["data"]["sessions"]["live"] == 3
    assert diagnostics_payload["data"]["sessions"]["active_or_processing"] == 3
    assert diagnostics_payload["data"]["sessions"]["states"] == {
        "queued": 1,
        "scanned": 2,
        "completed": 1,
        "failed": 1,
    }

    with app.app_context():
        db.session.remove()
        db.drop_all()
