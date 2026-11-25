import json
import os
import sys
import uuid
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import LodStandard, LodTemplate, Session as DBSession, User, UserMetadata, UserRole
from routes.msf_routes import msf_bp


class _DummyProjectService:
    def _translate_path(self, path, to_container=True):
        return path


class _DummySessionManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir

    def create_session_dirs(self):
        session_dir = self.base_dir / f"session_{uuid.uuid4().hex[:8]}"
        uploads_dir = session_dir / "uploads"
        outputs_dir = session_dir / "outputs"
        uploads_dir.mkdir(parents=True)
        outputs_dir.mkdir(parents=True)
        return (
            str(session_dir / "session.hdpc"),
            str(outputs_dir),
            str(uploads_dir),
            str(session_dir),
        )


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _seed_templates() -> None:
    db.session.add(
        LodTemplate(
            name="Default EDM",
            description="Test EDM template",
            standard=LodStandard.EDM,
            format="xml",
            is_default=True,
            content=(
                '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:edm="http://www.europeana.eu/schemas/edm/">'
                '<edm:ProvidedCHO rdf:about="{{ zenodo.links.html }}">'
                '<dc:title>{{ metadata.title }}</dc:title>'
                '<dc:identifier>{{ zenodo.metadata.prereserve_doi.doi }}</dc:identifier>'
                '</edm:ProvidedCHO></rdf:RDF>'
            ),
        )
    )
    db.session.add(
        LodTemplate(
            name="Default IIIF",
            description="Test IIIF template",
            standard=LodStandard.IIIF,
            format="json",
            is_default=True,
            content='{"type":"Manifest","label":{"en":["{{ metadata.title }}"]},"items":[]}',
        )
    )
    db.session.add(
        LodTemplate(
            name="Default METS",
            description="Test METS template",
            standard=LodStandard.METS,
            format="xml",
            is_default=True,
            content=(
                '<mets:mets xmlns:mets="http://www.loc.gov/METS/" '
                'xmlns:mods="http://www.loc.gov/mods/v3" '
                'xmlns:xlink="http://www.w3.org/1999/xlink">'
                '<mets:dmdSec ID="dmd1"><mets:mdWrap MDTYPE="MODS"><mets:xmlData>'
                '<mods:mods><mods:titleInfo><mods:title>{{ metadata.title }}</mods:title></mods:titleInfo>'
                '<mods:identifier type="doi">{{ zenodo.metadata.prereserve_doi.doi }}</mods:identifier>'
                '</mods:mods></mets:xmlData></mets:mdWrap></mets:dmdSec>'
                '</mets:mets>'
            ),
        )
    )
    db.session.commit()


def test_workflow_msf_analysis_reports_issues_and_applies_fixes(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["ENABLE_METIS_VALIDATION"] = False
    app.project_service = _DummyProjectService()

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")

    with app.app_context():
        db.create_all()
        _seed_templates()

        user = User(email="msf-workflow@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

        session_dir = tmp_path / "session"
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True)
        (uploads_dir / "asset.glb").write_bytes(b"glb")

        msf_path = uploads_dir / "upload.msf.csv"
        _write_text(
            str(msf_path),
            "filename,title,description,creator\n"
            " nested/path/asset.glb , Artifact Title ,, \n"
            "asset.glb,,,\n",
        )

        session_row = DBSession(
            user_id=user.id,
            session_dir=str(session_dir),
            hdpc_path=str(session_dir / "session.hdpc"),
            status="ready",
        )
        db.session.add(session_row)
        db.session.commit()
        session_id = session_row.id
        db.session.add(UserMetadata(
            session_id=session_id,
            field_name="zenodo_metadata_draft",
            field_value=json.dumps({"lod_mapping": {"iiif": {"3d": {
                "iiif:sceneId": {"source": "static", "value": "https://example.org/iiif/model/scene/1"},
                "iiif:pointX": {"source": "static", "value": 2},
                "iiif:latitude": {"source": "static", "value": 50},
                "iiif:longitude": {"source": "static", "value": 0},
            }}}}),
        ))
        db.session.commit()

    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    analyze_response = client.post(
        f"/api/v1/msf/workflow/session/{session_id}/analyze",
        headers=headers,
        json={},
    )
    assert analyze_response.status_code == 200
    analyze_payload = analyze_response.get_json()
    assert analyze_payload["success"] is True
    analysis = analyze_payload["data"]["analysis"]
    issue_ids = {item["id"] for item in analysis["issues"]}
    assert "duplicate_filename_rows" in issue_ids
    assert "missing_title_values" in issue_ids
    assert "missing_creator_values" in issue_ids
    assert "filename_normalization" in issue_ids
    assert analysis["recommended_fixes"]
    assert set(analysis["lod_samples"].keys()) == {"edm", "iiif", "mets"}
    iiif_sample = analysis["lod_samples"]["iiif"]
    assert iiif_sample["valid"] is True
    manifest = json.loads(iiif_sample["json"])
    assert manifest["navPlace"]["features"][0]["geometry"]["coordinates"] == [0, 50]
    scene = manifest["items"][0]
    assert scene["id"] == "https://example.org/iiif/model/scene/1"
    assert scene["items"][0]["items"][0]["target"]["selector"][0]["x"] == 2
    assert iiif_sample["validation"]["details"]["scene_count"] == 1
    assert "Template rendering returned empty result" not in (analysis["lod_samples"]["edm"].get("errors") or [])
    assert "METS Template rendering returned empty result" not in (analysis["lod_samples"]["mets"].get("errors") or [])

    apply_response = client.post(
        f"/api/v1/msf/workflow/session/{session_id}/analyze",
        headers=headers,
        json={
            "apply_selected_fixes": True,
            "selected_fix_ids": [
                "trim_whitespace",
                "normalize_filename_column",
                "resolve_duplicates",
            ],
        },
    )
    assert apply_response.status_code == 200
    apply_payload = apply_response.get_json()
    assert apply_payload["success"] is True
    apply_result = apply_payload["data"]["apply_result"]
    assert apply_result["applied"] is True
    assert apply_result["patched_msf_path"]
    assert os.path.exists(apply_result["patched_msf_path"])
    assert apply_result["patched_msf_path"].startswith(str(uploads_dir))

    with app.app_context():
        profile_record = UserMetadata.query.filter_by(
            session_id=session_id,
            field_name="msf_profile",
        ).first()
        assert profile_record is not None
        profile = json.loads(profile_record.field_value)
        assert profile["file_path"] == apply_result["patched_msf_path"]


def test_prepare_local_workflow_session_allows_guided_repair_on_invalid_preflight(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["ENABLE_METIS_VALIDATION"] = False
    app.config["STORAGE_MODE"] = "local"
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path / "local_input")
    app.project_service = _DummyProjectService()
    app.session_manager = _DummySessionManager(tmp_path)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")

    local_input = tmp_path / "local_input"
    local_input.mkdir()
    conflict_a = local_input / "a"
    conflict_b = local_input / "b"
    conflict_a.mkdir()
    conflict_b.mkdir()
    (conflict_a / "model_a.glb").write_bytes(b"a")
    (conflict_b / "model_a.glb").write_bytes(b"b")

    msf_path = local_input / "local_upload.csv"
    _write_text(
        str(msf_path),
        "filename,title\n"
        "unmatched-value,Artifact A\n",
    )

    with app.app_context():
        db.create_all()
        _seed_templates()

        user = User(email="local-guided@example.com", role=UserRole.ADMIN, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/msf/workflow/local/prepare",
        headers=headers,
        json={
            "msf_path": str(msf_path),
            "directory_path": "",
            "duplicate_policy": "merge_non_empty",
            "recursive": True,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["msf_preflight"]["is_valid"] is False
    analysis = payload["data"]["analysis"]
    issue_ids = {item["id"] for item in analysis["issues"]}
    assert "duplicate_directory_filenames" in issue_ids
    assert "filename_column_detection_low_confidence" in issue_ids
    assert analysis["workflow_state"]["requires_scan_start"] is True


def test_start_local_workflow_scan_accepts_after_guided_fix_stage(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["ENABLE_METIS_VALIDATION"] = False
    app.config["STORAGE_MODE"] = "local"
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path / "local_input")
    app.project_service = _DummyProjectService()
    app.session_manager = _DummySessionManager(tmp_path)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")

    local_input = tmp_path / "local_input"
    local_input.mkdir()
    (local_input / "asset.glb").write_bytes(b"glb")

    msf_path = local_input / "upload.csv"
    _write_text(
        str(msf_path),
        "filename,title,description\n"
        "nested/path/asset.glb,Primary,\n"
        "asset.glb,,Filled from duplicate row\n",
    )

    with app.app_context():
        db.create_all()
        _seed_templates()

        user = User(email="local-start@example.com", role=UserRole.ADMIN, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    prepare_response = client.post(
        "/api/v1/msf/workflow/local/prepare",
        headers=headers,
        json={
            "msf_path": str(msf_path),
            "directory_path": "",
            "duplicate_policy": "merge_non_empty",
            "recursive": True,
        },
    )
    assert prepare_response.status_code == 200
    prepare_payload = prepare_response.get_json()
    session_id = prepare_payload["data"]["session_id"]
    prepared_candidates = prepare_payload["data"]["msf_profile"].get("prepared_candidate_files") or []
    assert len(prepared_candidates) == 1
    assert prepared_candidates[0]["source_file_name"] == "asset.glb"

    fake_tasks = ModuleType("tasks")
    fake_tasks.start_upload_coordinator = SimpleNamespace(
        delay=lambda **kwargs: SimpleNamespace(id="task-local-123")
    )

    with patch.dict(sys.modules, {"tasks": fake_tasks}):
        start_response = client.post(
            f"/api/v1/msf/workflow/session/{session_id}/start-local-scan",
            headers=headers,
            json={},
        )

    assert start_response.status_code == 202
    start_payload = start_response.get_json()
    assert start_payload["success"] is True
    assert start_payload["data"]["task_id"] == "task-local-123"
    assert start_payload["data"]["msf_preflight"]["is_valid"] is True
    patched_path = start_payload["data"]["msf_preflight"]["patched_msf_path"]
    assert patched_path
    assert os.path.exists(patched_path)

    with app.app_context():
        from database.models import UserMetadata

        profile_record = UserMetadata.query.filter_by(session_id=session_id, field_name="msf_profile").first()
        assert profile_record is not None
        profile = json.loads(profile_record.field_value)
        assert profile["file_path"] == patched_path
        assert profile["scan_started"] is True
        prepared_candidates = profile.get("prepared_candidate_files") or []
        assert len(prepared_candidates) == 1
        assert prepared_candidates[0]["source_file_path"].endswith(os.path.join("local_input", "asset.glb"))


def test_workflow_msf_analysis_auto_applies_fix_dependencies(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["ENABLE_METIS_VALIDATION"] = False

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")

    with app.app_context():
        db.create_all()
        _seed_templates()

        user = User(email="dependency-fix@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

        session_dir = tmp_path / "session"
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True)
        (uploads_dir / "asset.glb").write_bytes(b"glb")

        msf_path = uploads_dir / "upload.msf.csv"
        _write_text(
            str(msf_path),
            "filename,title\n"
            "nested/path/asset.glb,Artifact Title\n"
            "asset.glb,\n",
        )

        session_row = DBSession(
            user_id=user.id,
            session_dir=str(session_dir),
            hdpc_path=str(session_dir / "session.hdpc"),
            status="ready",
        )
        db.session.add(session_row)
        db.session.commit()
        session_id = session_row.id

    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    apply_response = client.post(
        f"/api/v1/msf/workflow/session/{session_id}/analyze",
        headers=headers,
        json={
            "apply_selected_fixes": True,
            "selected_fix_ids": ["resolve_duplicates"],
        },
    )
    assert apply_response.status_code == 200
    payload = apply_response.get_json()
    assert payload["success"] is True
    assert payload["data"]["apply_result"]["applied"] is True
    assert payload["data"]["apply_result"]["selected_fix_ids"] == [
        "normalize_filename_column",
        "resolve_duplicates",
    ]
    issue_ids = {item["id"] for item in payload["data"]["analysis"]["issues"]}
    assert "duplicate_filename_rows" not in issue_ids


def test_local_workflow_analysis_can_update_directory_setup_in_place(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["ENABLE_METIS_VALIDATION"] = False
    app.config["STORAGE_MODE"] = "local"
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path / "local_input")
    app.project_service = _DummyProjectService()
    app.session_manager = _DummySessionManager(tmp_path)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")

    local_input = tmp_path / "local_input"
    local_input.mkdir()
    conflict_a = local_input / "a"
    conflict_b = local_input / "b"
    conflict_a.mkdir()
    conflict_b.mkdir()
    (conflict_a / "model_a.glb").write_bytes(b"a")
    (conflict_b / "model_a.glb").write_bytes(b"b")

    msf_path = local_input / "upload.csv"
    _write_text(
        str(msf_path),
        "filename,title\n"
        "model_a.glb,Artifact A\n",
    )

    with app.app_context():
        db.create_all()
        _seed_templates()

        user = User(email="local-setup@example.com", role=UserRole.ADMIN, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    prepare_response = client.post(
        "/api/v1/msf/workflow/local/prepare",
        headers=headers,
        json={
            "msf_path": str(msf_path),
            "directory_path": "",
            "duplicate_policy": "merge_non_empty",
            "recursive": True,
        },
    )
    assert prepare_response.status_code == 200
    session_id = prepare_response.get_json()["data"]["session_id"]

    update_response = client.post(
        f"/api/v1/msf/workflow/session/{session_id}/analyze",
        headers=headers,
        json={
            "directory_path": "a",
            "recursive": True,
        },
    )
    assert update_response.status_code == 200
    analysis = update_response.get_json()["data"]["analysis"]
    issue_ids = {item["id"] for item in analysis["issues"]}
    assert "duplicate_directory_filenames" not in issue_ids
    assert analysis["workflow_state"]["target_directory"].endswith(os.path.join("local_input", "a"))

    with app.app_context():
        from database.models import UserMetadata

        profile_record = UserMetadata.query.filter_by(session_id=session_id, field_name="msf_profile").first()
        profile = json.loads(profile_record.field_value)
        assert profile["directory_root"].endswith(os.path.join("local_input", "a"))
        prepared_candidates = profile.get("prepared_candidate_files") or []
        assert len(prepared_candidates) == 1
        assert prepared_candidates[0]["source_file_path"].endswith(os.path.join("local_input", "a", "model_a.glb"))
