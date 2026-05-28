import json
import os
import sqlite3
import sys
import tempfile
import types

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import User, UserRole
from middleware import setup_error_handlers
from routes.tools_routes import tools_bp
from services.zenodo_oai_harvest_history_service import get_harvest_entry
from services.zenodo_oai_harvest_service import (
    parse_oai_response,
    write_oai_harvest_shard,
)


OAI_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
  xmlns:oai_datacite="http://schema.datacite.org/oai/oai-1.1/"
  xmlns:datacite="http://datacite.org/schema/kernel-4">
  <responseDate>2026-05-26T12:00:00Z</responseDate>
  <request verb="ListRecords">https://zenodo.org/oai2d</request>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:zenodo.org:12345</identifier>
        <datestamp>2026-05-25T10:00:00Z</datestamp>
        <setSpec>user-3dbigdataspace</setSpec>
      </header>
      <metadata>
        <oai_datacite:oai_datacite>
          <oai_datacite:payload>
            <datacite:resource>
              <datacite:identifier identifierType="DOI">10.5281/zenodo.12345</datacite:identifier>
              <datacite:creators>
                <datacite:creator><datacite:creatorName>Curator One</datacite:creatorName></datacite:creator>
              </datacite:creators>
              <datacite:titles><datacite:title>Public 3D model</datacite:title></datacite:titles>
              <datacite:publisher>Zenodo</datacite:publisher>
              <datacite:publicationYear>2026</datacite:publicationYear>
              <datacite:subjects><datacite:subject>Objaverse</datacite:subject></datacite:subjects>
              <datacite:resourceType resourceTypeGeneral="Dataset">3D model</datacite:resourceType>
              <datacite:descriptions><datacite:description descriptionType="Abstract">A public Objaverse model.</datacite:description></datacite:descriptions>
              <datacite:rightsList><datacite:rights rightsURI="https://creativecommons.org/licenses/by/4.0/">CC-BY-4.0</datacite:rights></datacite:rightsList>
            </datacite:resource>
          </oai_datacite:payload>
        </oai_datacite:oai_datacite>
      </metadata>
    </record>
    <resumptionToken completeListSize="2" cursor="0">next-token</resumptionToken>
  </ListRecords>
</OAI-PMH>
"""


class _SessionManager:
    def __init__(self, root):
        self.root = root
        self.counter = 0

    def create_session_dirs(self):
        self.counter += 1
        session_dir = os.path.join(self.root, f"oai_session_{self.counter}")
        os.makedirs(session_dir, exist_ok=True)
        outputs = os.path.join(session_dir, "outputs")
        uploads = os.path.join(session_dir, "uploads")
        os.makedirs(outputs, exist_ok=True)
        os.makedirs(uploads, exist_ok=True)
        return os.path.join(session_dir, "session.hdpc"), outputs, uploads, session_dir


def _build_app():
    temp_dir = tempfile.mkdtemp(prefix="zenodo-oai-harvest-")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["SECRET_KEY"] = "test-secret-key"
    app.session_manager = _SessionManager(temp_dir)
    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")
    with app.app_context():
        db.create_all()
        user = User(email="harvester@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        user_id = int(user.id)
        token = create_access_token(identity=str(user.id))
    return app, user_id, token


def test_parse_oai_datacite_page_normalizes_core_metadata():
    parsed = parse_oai_response(OAI_PAGE)

    assert parsed["resumption_token"] == "next-token"
    assert parsed["complete_list_size"] == 2
    assert len(parsed["records"]) == 1
    record = parsed["records"][0]
    metadata = record["metadata"]["metadata"]
    assert record["oai_identifier"] == "oai:zenodo.org:12345"
    assert metadata["title"] == "Public 3D model"
    assert metadata["doi"] == "10.5281/zenodo.12345"
    assert metadata["creators"][0]["name"] == "Curator One"
    assert metadata["communities"] == [{"identifier": "3dbigdataspace"}]
    assert "raw_xml" in record


def test_write_oai_harvest_shard_creates_explorer_only_hdpc():
    app, user_id, _ = _build_app()
    parsed = parse_oai_response(OAI_PAGE)
    with app.app_context():
        user = db.session.get(User, user_id)
        shard = write_oai_harvest_shard(
            harvest_id="harvest-1",
            shard_index=1,
            records=parsed["records"],
            requested_by=user,
            window={"base_url": "https://zenodo.org/oai2d", "set_spec": "user-3dbigdataspace", "metadata_prefix": "oai_datacite"},
            manifest_summary={"harvest_id": "harvest-1", "record_count": 1},
        )

        assert shard["record_count"] == 1
        conn = sqlite3.connect(shard["hdpc_path"])
        try:
            row = conn.execute("SELECT record_status, record_origin, zenodo_record_id, zenodo_doi, record_metadata_json FROM zenodo_records").fetchone()
            snapshot = conn.execute("SELECT snapshot_stage, payload_json FROM zenodo_record_snapshots").fetchone()
            config = dict(conn.execute("SELECT config_key, config_value FROM project_configuration").fetchall())
        finally:
            conn.close()

    assert row[0] == "published"
    assert row[1] == "zenodo_oai_harvest"
    assert row[2] == "12345"
    assert row[3] == "10.5281/zenodo.12345"
    assert json.loads(row[4])["webhdp_oai_harvest"]["oai_identifier"] == "oai:zenodo.org:12345"
    assert snapshot[0] == "oai_pmh_record"
    assert "raw_xml" in json.loads(snapshot[1])
    assert config["oai.set_spec"] == "user-3dbigdataspace"


def test_oai_harvest_context_and_launch_do_not_require_zenodo_credential(monkeypatch):
    app, user_id, token = _build_app()
    client = app.test_client()

    context = client.get(
        "/api/v1/tools/zenodo-oai-harvest/context",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert context.status_code == 200
    assert context.get_json()["data"]["defaults"]["set_identifier"] == "3dbigdataspace"
    assert context.get_json()["data"]["defaults"]["metadata_prefix"] == "oai_datacite"

    class _Task:
        id = "oai-task-1"

    captured = {}

    def _delay(**kwargs):
        captured["kwargs"] = kwargs
        return _Task()

    dummy_tasks = types.SimpleNamespace(execute_zenodo_oai_harvest=types.SimpleNamespace(delay=_delay))
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    response = client.post(
        "/api/v1/tools/zenodo-oai-harvest/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "set_identifier": "3dbigdataspace",
            "metadata_prefix": "oai_datacite",
            "max_records": 100,
            "from_date": "2026-01-01",
            "until_date": "2026-01-31",
        },
    )

    assert response.status_code == 202
    payload = response.get_json()["data"]
    assert captured["kwargs"]["requester_user_id"] == user_id
    with app.app_context():
        entry = get_harvest_entry(payload["harvest_id"])
    assert entry["options"]["set_spec"] == "user-3dbigdataspace"
    assert entry["options"]["metadata_prefix"] == "oai_datacite"
    assert entry["options"]["max_records"] == 100
    assert entry["runtime"]["execution_target"] == "celery_local"
    assert "credential" not in entry
