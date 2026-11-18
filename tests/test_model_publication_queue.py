from concurrent.futures import ThreadPoolExecutor
import io
import time
from types import SimpleNamespace
from uuid import uuid4

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
import pytest

from database.database import db
from database.models import SystemConfig, User
from middleware import setup_error_handlers
from routes.model_publication_routes import LIBRARY, model_publication_bp, sample_catalog
from services import model_publication_queue as queue
from services.model_publication_accounts import DEMO_CAPABILITY, demo_config_key


def test_queue_counts_and_reserves_demo_capacity(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config["MODEL_PUBLICATION_ENABLED"] = True
    (tmp_path / ".heartbeat").touch()
    monkeypatch.setattr(queue.shutil, "disk_usage", lambda _: SimpleNamespace(free=4 * 1024**3))
    with app.app_context():
        status = queue.snapshot(tmp_path)
        assert (status["queued"], status["running"], status["capacity"], status["ready"]) == (0, 0, 4, True)
        assert abs(status["updated"] - time.time()) < 2
        limit = queue.MAX_ACTIVE - queue.DEMO_QUEUE_RESERVE
        for index in range(limit):
            identity, _ = queue.reserve(tmp_path, user_id=index + 10, sign_in="regular", request_key="first",
                                        demo_window=0, parameters={"sample_id": "bronze-seal"})
            queue.enqueue(tmp_path, identity)
        with pytest.raises(queue.QueueError) as full:
            queue.reserve(tmp_path, user_id=999, sign_in="regular", request_key="first",
                          demo_window=0, parameters={"sample_id": "bronze-seal"})
        assert full.value.status == 429
        for index in range(queue.DEMO_QUEUE_RESERVE):
            identity, _ = queue.reserve(tmp_path, user_id=1, sign_in=str(index), request_key="first",
                                        demo_window=900, parameters={"sample_id": "bronze-seal"})
            queue.enqueue(tmp_path, identity)
        queue.claim(tmp_path)
        status = queue.snapshot(tmp_path)
        assert status["queued"] == queue.MAX_ACTIVE - 1
        assert status["running"] == 1
        assert set(status) == {"queued", "running", "capacity", "ready", "updated"}


def test_concurrent_submissions_are_fifo_and_recover_after_interruption(tmp_path):
    def submit(index):
        sign_in = str(index)
        identity, created = queue.reserve(tmp_path, user_id=1, sign_in=sign_in, request_key=uuid4().hex,
                                          demo_window=900, parameters={"sample_id": "bronze-seal"})
        assert created
        queue.enqueue(tmp_path, identity)
        return identity, sign_in

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(submit, range(20)))
    assert len({identity for identity, _ in responses}) == 20
    expected_order = [item["id"] for item in reversed(queue.get_jobs(tmp_path, user_id=1))]
    for identity, sign_in in responses:
        assert [item["id"] for item in queue.get_jobs(tmp_path, user_id=1, sign_in=sign_in)] == [identity]
    assert sorted(queue.serialize(item)["position"] for item in queue.get_jobs(tmp_path, user_id=1)) == list(range(1, 21))
    assert queue.claim(tmp_path)["id"] == expected_order[0]
    queue.recover(tmp_path)
    assert [queue.claim(tmp_path)["id"] for _ in range(20)] == expected_order
    assert queue.claim(tmp_path) is None


def test_shared_demo_only_accepts_official_samples_and_isolates_results(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, JWT_SECRET_KEY="unit-test-signing-key" * 3,
                      SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", MODEL_PUBLICATION_ENABLED=True,
                      MODEL_PUBLICATION_ROOT=tmp_path)
    monkeypatch.setenv("ZENODO_SANDBOX_API_KEY", "sample-linked-secret")
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(model_publication_bp, url_prefix="/api/v1/model-publication")
    setup_error_handlers(app)
    (tmp_path / ".heartbeat").touch()
    with app.app_context():
        db.create_all()
        user = User(email="demo@webhdp.invalid", password_hash="unused", is_verified=True)
        user.set_capabilities([DEMO_CAPABILITY])
        db.session.add(user)
        db.session.flush()
        db.session.add(SystemConfig(key=demo_config_key(user.id), value=str(int(time.time()) + 900)))
        db.session.commit()
        first_token = create_access_token(identity=str(user.id))
        second_token = create_access_token(identity=str(user.id))
    first = {"Authorization": "Bearer " + first_token}
    second = {"Authorization": "Bearer " + second_token}
    client = app.test_client()
    url = "/api/v1/model-publication/jobs"
    sample = sample_catalog()[0]
    assert client.post(url, headers=first, data={"sample_id": sample["id"], "title": "Unknown"}).status_code == 400
    assert client.post(url, headers=first, data={"archive": (io.BytesIO(b"elsewhere"), "custom.zip")}).status_code == 400
    first["Idempotency-Key"] = uuid4().hex
    start = client.post(url, headers=first, data={"archive": ((LIBRARY / sample["filename"]).open("rb"), "download.zip")})
    assert start.status_code == 202
    job = start.get_json()["data"]["job"]
    retry = client.post(url, headers=first, data={"sample_id": sample["id"]})
    assert retry.status_code == 200 and retry.get_json()["data"]["job"]["id"] == job["id"]
    assert client.get(f"{url}/{job['id']}", headers=second).status_code == 404
    assert client.get(url, headers=second).get_json()["data"]["jobs"] == []
    status_url = "/api/v1/model-publication/queue"
    assert client.get(status_url).status_code == 401
    aggregate = client.get(status_url, headers=second)
    assert aggregate.get_json()["data"]["queued"] == 1
    assert "no-store" in aggregate.headers["Cache-Control"]
    assert job["id"].encode() not in aggregate.data
    assert b"sample-linked-secret" not in client.get("/api/v1/model-publication/availability", headers=first).data


def test_file_upload_retries_from_the_start_after_sandbox_rate_limit(monkeypatch):
    from types import SimpleNamespace

    from services import model_publication_worker as worker
    from external_code.webhdp_link_zenodo.runner import SandboxClient

    body = io.BytesIO(b"model data")
    sent = []

    def request(_, method, url, *, expected, **kwargs):
        sent.append(kwargs["data"].read())
        return SimpleNamespace(status_code=429 if len(sent) == 1 else 200,
                               headers={"Retry-After": "1"})

    monkeypatch.setattr(SandboxClient, "request", request)
    monkeypatch.setattr(worker, "_retry_after", 0)
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    client = worker.DraftClient("test-token")
    assert client.request("PUT", "https://sandbox.zenodo.org/api/files/example/model.zip",
                          expected={200}, data=body).status_code == 200
    assert sent == [b"model data", b"model data"]
