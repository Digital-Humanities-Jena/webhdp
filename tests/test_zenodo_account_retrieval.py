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
from services.zenodo_account_retrieval_history_service import get_retrieval_entry
from services.zenodo_account_retrieval_service import (
    ZenodoAccountRetrievalRunner,
    sanitize_for_storage,
    write_retrieval_shard,
)
from services.zenodo_credential_service import ZenodoCredentialService


class _SessionManager:
    def __init__(self, root):
        self.root = root
        self.counter = 0

    def create_session_dirs(self):
        self.counter += 1
        session_dir = os.path.join(self.root, f"retrieval_session_{self.counter}")
        os.makedirs(session_dir, exist_ok=True)
        outputs = os.path.join(session_dir, "outputs")
        uploads = os.path.join(session_dir, "uploads")
        os.makedirs(outputs, exist_ok=True)
        os.makedirs(uploads, exist_ok=True)
        return os.path.join(session_dir, "session.hdpc"), outputs, uploads, session_dir


def _build_app():
    temp_dir = tempfile.mkdtemp(prefix="zenodo-account-retrieval-")
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
        user = User(email="retriever@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        credential = ZenodoCredentialService().create_credential(
            user_id=user.id,
            environment="production",
            token="super-secret-token",
            name="Production retrieval key",
            actor_user_id=user.id,
        )
        user_id = int(user.id)
        credential_id = int(credential.id)
        token = create_access_token(identity=str(user.id))
    return app, user_id, credential_id, token


def test_retrieval_context_lists_accessible_credentials_without_secret():
    app, _, credential_id, token = _build_app()
    client = app.test_client()

    response = client.get(
        "/api/v1/tools/zenodo-account-retrieval/context",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    credentials = payload["data"]["credentials"]
    assert credentials[0]["id"] == credential_id
    assert payload["data"]["defaults"]["retrieval_mode"] == "full"
    assert payload["data"]["defaults"]["execution_target"] == "celery_local"
    assert any(target["id"] == "hpc_link" and target["queueable"] is False for target in payload["data"]["execution_targets"])
    assert "super-secret-token" not in json.dumps(payload)


def test_retrieval_preflight_reports_historical_backfill_and_hpc_proxy_warning():
    app, _, credential_id, token = _build_app()
    client = app.test_client()

    response = client.post(
        "/api/v1/tools/zenodo-account-retrieval/preflight",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "credential_id": credential_id,
            "retrieval_mode": "historical_backfill",
            "execution_target": "hpc_link",
            "end_date": "2024-03-26",
            "initial_window_days": 1,
            "request_retries": 5,
            "request_timeout_seconds": 45,
        },
    )

    assert response.status_code == 200
    preflight = response.get_json()["data"]["preflight"]
    assert preflight["retrieval_mode"] == "historical_backfill"
    assert preflight["execution_target"] == "hpc_link"
    assert preflight["queueable"] is False
    assert preflight["date_window"]["end"] == "2024-03-26T23:59:59Z"
    assert preflight["runtime_options"]["initial_window_days"] == 1
    assert preflight["runtime_options"]["request_retries"] == 5
    assert preflight["runtime_options"]["request_timeout_seconds"] == 45.0
    assert "NO_PROXY/no_proxy" in json.dumps(preflight)
    assert "super-secret-token" not in json.dumps(preflight)


def test_launch_retrieval_persists_history_without_token(monkeypatch):
    app, user_id, credential_id, token = _build_app()
    client = app.test_client()

    class _Task:
        id = "retrieval-task-1"

    captured = {}
    def _delay(**kwargs):
        captured["kwargs"] = kwargs
        return _Task()

    dummy_tasks = types.SimpleNamespace(
        execute_zenodo_account_retrieval=types.SimpleNamespace(delay=_delay)
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    response = client.post(
        "/api/v1/tools/zenodo-account-retrieval/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "credential_id": credential_id,
            "max_records": 11000,
            "retrieval_mode": "historical_backfill",
            "execution_target": "celery_local",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "initial_window_days": 7,
            "request_retries": 4,
            "request_timeout_seconds": 60,
        },
    )

    assert response.status_code == 202
    payload = response.get_json()["data"]
    assert captured["kwargs"]["credential_id"] == credential_id
    assert captured["kwargs"]["requester_user_id"] == user_id
    with app.app_context():
        entry = get_retrieval_entry(payload["retrieval_id"])
    assert entry["credential_id"] == credential_id
    assert entry["options"]["max_records"] == 11000
    assert entry["options"]["retrieval_mode"] == "historical_backfill"
    assert entry["options"]["start_datetime"] == "2026-01-01T00:00:00Z"
    assert entry["options"]["end_datetime"] == "2026-01-31T23:59:59Z"
    assert entry["options"]["initial_window_days"] == 7
    assert entry["options"]["request_retries"] == 4
    assert entry["options"]["request_timeout_seconds"] == 60.0
    assert entry["runtime"]["execution_target"] == "celery_local"
    assert entry["runtime"]["token_source"] == "credential"
    assert "shard_root" in entry["runtime"]
    assert "script_version" in entry["runtime"]
    assert entry["runtime"]["process"]["pid"]
    assert entry["preflight"]["queueable"] is True
    assert entry["summary"]["max_records"] == 11000
    assert entry["requested_by"]["email"] == "retriever@example.com"
    assert "super-secret-token" not in json.dumps(entry)


def test_launch_retrieval_rejects_hpc_execution_until_runner_exists():
    app, _, credential_id, token = _build_app()
    client = app.test_client()

    response = client.post(
        "/api/v1/tools/zenodo-account-retrieval/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={"credential_id": credential_id, "execution_target": "hpc_link"},
    )

    assert response.status_code == 400
    assert "preflight" in json.dumps(response.get_json()).lower()


def test_launch_retrieval_does_not_overwrite_inline_completion(monkeypatch):
    app, _, credential_id, token = _build_app()
    client = app.test_client()

    class _Task:
        id = "inline-task-1"

    def _delay(**kwargs):
        from services.zenodo_account_retrieval_history_service import update_retrieval_entry

        update_retrieval_entry(
            kwargs["retrieval_id"],
            state="SUCCESS",
            status="Zenodo account retrieval completed",
            progress={"percent": 100},
            summary={"retrieved_records": 1},
        )
        return _Task()

    dummy_tasks = types.SimpleNamespace(
        execute_zenodo_account_retrieval=types.SimpleNamespace(delay=_delay)
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    response = client.post(
        "/api/v1/tools/zenodo-account-retrieval/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={"credential_id": credential_id, "max_records": 1},
    )

    assert response.status_code == 202
    retrieval_id = response.get_json()["data"]["retrieval_id"]
    with app.app_context():
        entry = get_retrieval_entry(retrieval_id)
    assert entry["state"] == "SUCCESS"
    assert entry["status"] == "Zenodo account retrieval completed"
    assert entry["task_id"] == "inline-task-1"


def test_retrieval_status_response_hides_seen_dedupe_keys():
    app, user_id, credential_id, token = _build_app()
    client = app.test_client()
    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        record_retrieval_launch(
            retrieval_id="public-checkpoint-test",
            task_id=None,
            credential_id=credential_id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential_id},
        )
        update_retrieval_entry(
            "public-checkpoint-test",
            checkpoint={"pending_windows": [], "seen_keys": ["published:1", "published:2"]},
        )

    response = client.get(
        "/api/v1/tools/zenodo-account-retrieval/jobs/public-checkpoint-test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    checkpoint = response.get_json()["data"]["checkpoint"]
    assert checkpoint["seen_count"] == 2
    assert "seen_keys" not in checkpoint


def test_sanitize_for_storage_removes_access_tokens():
    payload = {
        "links": {
            "self": "https://zenodo.org/api/deposit/depositions/1?access_token=secret&page=1",
        },
        "access_token": "secret",
        "nested": [{"token": "secret", "url": "https://example.test/path?x=1&access_token=secret"}],
    }

    sanitized = sanitize_for_storage(payload)

    serialized = json.dumps(sanitized)
    assert "secret" not in serialized
    assert "access_token" not in serialized
    assert "page=1" in serialized
    assert "x=1" in serialized


def test_write_retrieval_shard_marks_records_and_files_as_retrieved_metadata_only():
    app, user_id, credential_id, _ = _build_app()
    with app.app_context():
        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        shard = write_retrieval_shard(
            retrieval_id="retrieval-1",
            shard_index=1,
            environment="production",
            requested_by=user,
            credential=credential,
            window={"status": "published", "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
            manifest_summary={"retrieval_id": "retrieval-1", "shard_index": 1},
            records=[
                {
                    "id": 123,
                    "created": "2026-01-01T12:00:00Z",
                    "modified": "2026-01-01T12:10:00Z",
                    "metadata": {"title": "Retrieved record", "doi": "10.5281/zenodo.123"},
                    "links": {"html": "https://zenodo.org/records/123?access_token=secret", "edit": "https://zenodo.org/api/deposit/depositions/123/actions/edit"},
                    "files": [{"id": "file-1", "filename": "model.glb", "filesize": 42, "checksum": "md5:abc"}],
                }
            ],
        )

        conn = sqlite3.connect(shard["hdpc_path"])
        try:
            record = conn.execute("SELECT record_origin, record_metadata_json FROM zenodo_records").fetchone()
            assert record[0] == "zenodo_retrieval"
            assert "secret" not in record[1]
            metadata = json.loads(record[1])
            assert metadata["webhdp_retrieval"]["capabilities"]["had_edit_rights"] is True
            file_row = conn.execute("SELECT upload_status, zenodo_file_key FROM record_files_map").fetchone()
            assert file_row == ("retrieved_metadata_only", "model.glb")
        finally:
            conn.close()


class _Response:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text or f"HTTP {self.status_code}")


def test_runner_harvests_page_by_page_without_page_100_preflight(monkeypatch):
    app, user_id, credential_id, _ = _build_app()
    calls = []

    class _Http:
        @staticmethod
        def get(url, headers=None, params=None, timeout=None):
            calls.append(dict(params or {}))
            if params.get("page") == 100 and len(calls) == 1:
                return _Response(payload=[{"id": index} for index in range(100)])
            return _Response(payload=[])

    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch

        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        record_retrieval_launch(
            retrieval_id="split-test",
            task_id=None,
            credential_id=credential.id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential.id},
        )
        from services.zenodo_account_retrieval_history_service import update_retrieval_entry

        update_retrieval_entry(
            "split-test",
            checkpoint={
                "pending_windows": [
                    {"status": "published", "start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}
                ]
            },
        )
        runner = ZenodoAccountRetrievalRunner(
            retrieval_id="split-test",
            credential=credential,
            requester=user,
            http=_Http,
            sleep_func=lambda seconds: None,
            min_interval_seconds=0,
        )
        result = runner.run(token="super-secret-token")

    assert result["status"] == "completed"
    assert [call.get("page") for call in calls] == [1]


def test_runner_defers_window_when_first_page_times_out():
    app, user_id, credential_id, _ = _build_app()
    calls = []

    class _Http:
        @staticmethod
        def get(url, headers=None, params=None, timeout=None):
            calls.append(dict(params or {}))
            if params.get("page") == 1 and len(calls) <= 3:
                return _Response(status_code=504, payload={}, text="Gateway Time-out")
            return _Response(payload=[])

    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        record_retrieval_launch(
            retrieval_id="timeout-split-test",
            task_id=None,
            credential_id=credential.id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential.id},
        )
        update_retrieval_entry(
            "timeout-split-test",
            checkpoint={
                "pending_windows": [
                    {"status": "published", "start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}
                ]
            },
        )
        runner = ZenodoAccountRetrievalRunner(
            retrieval_id="timeout-split-test",
            credential=credential,
            requester=user,
            http=_Http,
            sleep_func=lambda seconds: None,
            min_interval_seconds=0,
        )
        result = runner.run(token="super-secret-token")

    assert result["status"] == "completed"
    assert result["summary"]["split_windows"] == 0
    assert result["summary"]["deferred_windows"] == 1
    assert len([call for call in calls if call.get("page") == 1]) >= 4


def test_runner_splits_window_when_harvest_page_times_out():
    app, user_id, credential_id, _ = _build_app()
    calls = []

    class _Http:
        @staticmethod
        def get(url, headers=None, params=None, timeout=None):
            params = dict(params or {})
            calls.append(params)
            page = int(params.get("page") or 1)
            if page == 100:
                return _Response(payload=[])
            if page in {1, 2, 3, 4} and len([call for call in calls if int(call.get("page") or 1) == page]) == 1:
                return _Response(payload=[{"id": f"{page}-{index}"} for index in range(100)])
            if page == 5:
                return _Response(status_code=504, payload={}, text="Gateway Time-out")
            return _Response(payload=[])

    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        record_retrieval_launch(
            retrieval_id="harvest-timeout-split-test",
            task_id=None,
            credential_id=credential.id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential.id},
        )
        update_retrieval_entry(
            "harvest-timeout-split-test",
            checkpoint={
                "pending_windows": [
                    {"status": "published", "start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}
                ]
            },
        )
        runner = ZenodoAccountRetrievalRunner(
            retrieval_id="harvest-timeout-split-test",
            credential=credential,
            requester=user,
            http=_Http,
            sleep_func=lambda seconds: None,
            min_interval_seconds=0,
        )
        result = runner.run(token="super-secret-token")

    assert result["status"] == "completed"
    assert result["summary"]["retrieved_records"] == 400
    assert result["summary"]["split_windows"] >= 1
    assert result["summary"]["pages_retrieved"] == 4


def test_runner_splits_window_when_page_limit_returns_generic_bad_request():
    app, user_id, credential_id, _ = _build_app()
    calls = []

    class _Http:
        @staticmethod
        def get(url, headers=None, params=None, timeout=None):
            params = dict(params or {})
            calls.append(params)
            if int(params.get("page") or 1) == 101:
                return _Response(status_code=400, payload={}, text="BAD REQUEST")
            return _Response(payload=[])

    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        record_retrieval_launch(
            retrieval_id="generic-page-limit-split-test",
            task_id=None,
            credential_id=credential.id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential.id},
        )
        update_retrieval_entry(
            "generic-page-limit-split-test",
            checkpoint={
                "active_window": {
                    "status": "published",
                    "start": "2026-01-01T00:00:00Z",
                    "end": "2026-01-31T23:59:59Z",
                    "next_page": 101,
                },
                "pending_windows": [],
            },
        )
        runner = ZenodoAccountRetrievalRunner(
            retrieval_id="generic-page-limit-split-test",
            credential=credential,
            requester=user,
            http=_Http,
            sleep_func=lambda seconds: None,
            min_interval_seconds=0,
        )
        result = runner.run(token="super-secret-token")

    assert result["status"] == "completed"
    assert result["summary"]["split_windows"] >= 1
    assert [call.get("page") for call in calls] == [101, 1, 1]


def test_runner_stops_at_configured_max_records():
    app, user_id, credential_id, _ = _build_app()

    class _Http:
        @staticmethod
        def get(url, headers=None, params=None, timeout=None):
            page = int(params.get("page") or 1)
            if page == 100:
                return _Response(payload=[])
            if page in {1, 2}:
                base = 1 if page == 1 else 101
                return _Response(payload=[{"id": base + index, "metadata": {"title": f"Record {base + index}"}} for index in range(100)])
            return _Response(payload=[])

    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        record_retrieval_launch(
            retrieval_id="limit-test",
            task_id=None,
            credential_id=credential.id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential.id},
            max_records=150,
        )
        update_retrieval_entry(
            "limit-test",
            checkpoint={
                "pending_windows": [
                    {"status": "published", "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"}
                ]
            },
        )
        runner = ZenodoAccountRetrievalRunner(
            retrieval_id="limit-test",
            credential=credential,
            requester=user,
            http=_Http,
            sleep_func=lambda seconds: None,
            min_interval_seconds=0,
        )
        result = runner.run(token="super-secret-token")

    assert result["status"] == "completed: maximum record limit reached"
    assert result["summary"]["retrieved_records"] == 150
    assert result["summary"]["limit_reached"] is True
    assert sum(shard["record_count"] for shard in result["manifest"]["shards"]) == 150


def test_limited_runner_updates_collection_timestamps_for_incremental_followup():
    app, user_id, credential_id, _ = _build_app()

    class _Http:
        @staticmethod
        def get(url, headers=None, params=None, timeout=None):
            page = int(params.get("page") or 1)
            if page == 1:
                return _Response(
                    payload=[
                        {"id": 701, "created": "2026-04-10T10:00:00Z", "modified": "2026-04-10T11:00:00Z", "metadata": {"title": "First"}},
                        {"id": 702, "created": "2026-04-11T10:00:00Z", "modified": "2026-04-11T12:00:00Z", "metadata": {"title": "Second"}},
                    ]
                )
            return _Response(payload=[])

    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        record_retrieval_launch(
            retrieval_id="limited-collection-test",
            task_id=None,
            credential_id=credential.id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential.id},
            max_records=2,
        )
        update_retrieval_entry(
            "limited-collection-test",
            checkpoint={
                "pending_windows": [
                    {"status": "published", "start": "2026-04-01T00:00:00Z", "end": "2026-04-30T23:59:59Z"}
                ]
            },
        )
        runner = ZenodoAccountRetrievalRunner(
            retrieval_id="limited-collection-test",
            credential=credential,
            requester=user,
            http=_Http,
            sleep_func=lambda seconds: None,
            min_interval_seconds=0,
        )
        result = runner.run(token="super-secret-token")
        entry = get_retrieval_entry("limited-collection-test")

    assert result["summary"]["retrieved_records"] == 2
    assert entry["collection"]["record_count"] == 2
    assert entry["collection"]["latest_created"] == "2026-04-11T10:00:00Z"
    assert entry["collection"]["latest_modified"] == "2026-04-11T12:00:00Z"


def test_runner_deduplicates_records_across_overlapping_windows():
    app, user_id, credential_id, _ = _build_app()

    class _Http:
        @staticmethod
        def get(url, headers=None, params=None, timeout=None):
            page = int(params.get("page") or 1)
            if page == 1:
                return _Response(payload=[{"id": index, "metadata": {"title": f"Record {index}"}} for index in range(1, 101)])
            return _Response(payload=[])

    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        record_retrieval_launch(
            retrieval_id="dedupe-test",
            task_id=None,
            credential_id=credential.id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential.id},
        )
        update_retrieval_entry(
            "dedupe-test",
            checkpoint={
                "pending_windows": [
                    {"status": "published", "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
                    {"status": "published", "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
                ]
            },
        )
        runner = ZenodoAccountRetrievalRunner(
            retrieval_id="dedupe-test",
            credential=credential,
            requester=user,
            http=_Http,
            sleep_func=lambda seconds: None,
            min_interval_seconds=0,
        )
        result = runner.run(token="super-secret-token")

    assert result["status"] == "completed"
    assert result["summary"]["retrieved_records"] == 100
    assert result["summary"]["duplicate_records_skipped"] == 100
    assert sum(shard["record_count"] for shard in result["manifest"]["shards"]) == 100


def test_incremental_launch_uses_latest_previous_collection(monkeypatch):
    app, user_id, credential_id, token = _build_app()
    client = app.test_client()

    class _Task:
        id = "incremental-task-1"

    captured = {}

    def _delay(**kwargs):
        captured["kwargs"] = kwargs
        return _Task()

    dummy_tasks = types.SimpleNamespace(
        execute_zenodo_account_retrieval=types.SimpleNamespace(delay=_delay)
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        record_retrieval_launch(
            retrieval_id="base-retrieval",
            task_id=None,
            credential_id=credential_id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential_id},
        )
        update_retrieval_entry(
            "base-retrieval",
            state="SUCCESS",
            status="completed",
            summary={"retrieved_records": 2, "latest_created": "2026-04-20T12:00:00Z", "latest_modified": "2026-04-20T13:00:00Z"},
            manifest={"retrieval_id": "base-retrieval", "shards": []},
        )

    response = client.post(
        "/api/v1/tools/zenodo-account-retrieval/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={"credential_id": credential_id, "sync_mode": "incremental", "incremental_overlap_hours": 6, "max_records": 5},
    )

    assert response.status_code == 202
    payload = response.get_json()["data"]
    assert payload["sync_mode"] == "incremental"
    assert payload["parent_retrieval_id"] == "base-retrieval"
    assert payload["incremental_since"] == "2026-04-20T12:00:00Z"
    with app.app_context():
        entry = get_retrieval_entry(payload["retrieval_id"])
    assert entry["options"]["sync_mode"] == "incremental"
    assert entry["options"]["parent_retrieval_id"] == "base-retrieval"
    assert entry["options"]["start_datetime"] == "2026-04-20T06:00:00Z"
    assert captured["kwargs"]["credential_id"] == credential_id


def test_collection_search_and_compaction_routes():
    app, user_id, credential_id, token = _build_app()
    client = app.test_client()
    with app.app_context():
        from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry

        user = db.session.get(User, user_id)
        credential = ZenodoCredentialService().require_credential_by_id(credential_id)
        shard = write_retrieval_shard(
            retrieval_id="collection-routes",
            shard_index=1,
            environment="production",
            requested_by=user,
            credential=credential,
            window={"status": "published", "start": "2026-04-01T00:00:00Z", "end": "2026-04-02T00:00:00Z"},
            manifest_summary={"retrieval_id": "collection-routes", "shard_index": 1, "sync_mode": "full"},
            records=[
                {
                    "id": 501,
                    "created": "2026-04-01T12:00:00Z",
                    "modified": "2026-04-01T12:10:00Z",
                    "metadata": {"title": "Searchable amphora", "description": "Objaverse candidate", "communities": []},
                    "files": [{"id": "file-501", "filename": "model.glb", "filesize": 10}],
                    "links": {"edit": "https://zenodo.org/edit/501"},
                },
                {"id": 502, "created": "2026-04-01T13:00:00Z", "modified": "2026-04-01T13:10:00Z", "metadata": {"title": "Other vessel"}, "links": {}},
            ],
        )
        record_retrieval_launch(
            retrieval_id="collection-routes",
            task_id=None,
            credential_id=credential_id,
            environment="production",
            requested_by_user_id=user.id,
            requested_by_email=user.email,
            credential_summary={"credential_id": credential_id},
        )
        update_retrieval_entry(
            "collection-routes",
            state="SUCCESS",
            status="completed",
            summary={"retrieved_records": 2, "earliest_created": "2026-04-01T12:00:00Z", "latest_created": "2026-04-01T13:00:00Z"},
            manifest={"retrieval_id": "collection-routes", "shards": [shard]},
        )

    search_response = client.get(
        "/api/v1/tools/zenodo-account-retrieval/jobs/collection-routes/records?q=amphora&capability=editable",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()["data"]
    assert search_payload["total"] == 1
    assert search_payload["records"][0]["zenodo_record_id"] == "501"

    coverage_response = client.get(
        f"/api/v1/tools/zenodo-account-retrieval/coverage?credential_id={credential_id}&environment=production",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert coverage_response.status_code == 200
    coverage = coverage_response.get_json()["data"]["coverage"]
    assert coverage["collection_count"] == 1
    assert coverage["earliest_created"] == "2026-04-01T12:00:00Z"

    diagnostics_response = client.get(
        "/api/v1/tools/zenodo-account-retrieval/jobs/collection-routes/diagnostics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.get_json()["data"]["diagnostics"]
    assert diagnostics["process_health"]["status"] == "exited"
    assert diagnostics["runtime"]["token_source"] == "credential"

    detector_response = client.get(
        "/api/v1/tools/zenodo-account-retrieval/jobs/collection-routes/detectors?detector=community_migration_candidates&target_community=3dbigdataspace",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detector_response.status_code == 200
    detector_payload = detector_response.get_json()["data"]
    assert detector_payload["source"] == "local_retrieval_shards"
    assert detector_payload["total"] == 1
    assert detector_payload["candidates"][0]["zenodo_record_id"] == "501"

    detector_export = client.get(
        "/api/v1/tools/zenodo-account-retrieval/jobs/collection-routes/detectors/export?detector=community_migration_candidates&target_community=3dbigdataspace",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detector_export.status_code == 200
    assert "Searchable amphora" in detector_export.get_data(as_text=True)

    compact_response = client.post(
        "/api/v1/tools/zenodo-account-retrieval/jobs/collection-routes/compact",
        headers={"Authorization": f"Bearer {token}"},
        json={"target_records_per_shard": 100},
    )
    assert compact_response.status_code == 200
    compact_payload = compact_response.get_json()["data"]
    assert compact_payload["compaction"]["created_compacted_shards"] == 1
    schedule_response = client.patch(
        "/api/v1/tools/zenodo-account-retrieval/jobs/collection-routes/schedule",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True, "frequency": "weekly", "incremental_overlap_hours": 12},
    )
    assert schedule_response.status_code == 200
    assert schedule_response.get_json()["data"]["collection"]["schedule"]["frequency"] == "weekly"
    with app.app_context():
        entry = get_retrieval_entry("collection-routes")
    assert len(entry["manifest"]["compacted_shards"]) == 1
    assert entry["collection"]["schedule"]["incremental_overlap_hours"] == 12
