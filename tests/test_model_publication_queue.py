from concurrent.futures import ThreadPoolExecutor
import io
import json
import struct
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


def test_model_workspace_and_daily_caps_span_sample_and_sandbox_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(queue.shutil, "disk_usage", lambda _: SimpleNamespace(free=4 * 1024**3))

    def reserve(user, key, **parameters):
        return queue.reserve(tmp_path, user_id=user, sign_in="owner", request_key=str(key), demo_window=0,
                             parameters=parameters)[0]

    first = reserve(1, 1, run_mode="sandbox")
    reserve(1, 2, run_mode="sandbox")
    with pytest.raises(queue.QueueError) as storage:
        reserve(1, 3, run_mode="practice", practice_sample_id="glazed-bowl")
    assert storage.value.code == "MODEL_PUBLICATION_STORAGE_QUOTA"
    assert storage.value.details["usage"]["stored_bytes"] == 2 * queue.RUN_RESERVATION
    queue.abandon_upload(tmp_path, first)
    reserve(1, 3, run_mode="practice", practice_sample_id="glazed-bowl")

    for attempt in range(queue.ACCOUNT_DAILY_JOBS):
        job = reserve(2, attempt, run_mode="practice", practice_sample_id="glazed-bowl")
        queue.enqueue(tmp_path, job)
        assert queue.claim(tmp_path)["id"] == job
        queue.update(tmp_path, job, "completed")
        queue.trim(tmp_path, job)
    with pytest.raises(queue.QueueError) as daily:
        reserve(2, "limit", run_mode="sandbox")
    assert daily.value.code == "MODEL_PUBLICATION_DAILY_QUOTA"
    assert daily.value.details["usage"]["daily_reset_at"] > time.time()
    assert queue.account_usage(tmp_path, 3)["accepted_last_24_hours"] == 0


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


def test_tutorial_runs_real_sample_privately_and_can_be_replayed(tmp_path, monkeypatch):
    from cryptography.fernet import InvalidToken

    from routes import model_publication_routes
    from services import model_publication_worker as worker

    app = Flask(__name__)
    app.config.update(TESTING=True, JWT_SECRET_KEY="unit-test-signing-key" * 3,
                      SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", MODEL_PUBLICATION_ENABLED=True,
                      MODEL_PUBLICATION_ROOT=tmp_path)
    db.init_app(app)
    JWTManager(app)
    publication = "/api/v1/model-publication"
    app.register_blueprint(model_publication_bp, url_prefix=publication)
    setup_error_handlers(app)
    (tmp_path / ".heartbeat").touch()
    with app.app_context():
        db.create_all()
        learner = User(email="learner@example.org", password_hash="unused", is_verified=True)
        visitor = User(email="visitor@example.org", password_hash="unused", is_verified=False)
        demo = User(email="model-demo-abcd0123@webhdp.invalid", password_hash="unused", is_verified=True)
        db.session.add_all([learner, visitor, demo])
        db.session.commit()
        learner_id = learner.id
        headers = [{"Authorization": "Bearer " + create_access_token(identity=str(user.id))}
                   for user in (learner, visitor, demo)]
    own, other, demo = headers
    client = app.test_client()
    url = publication + "/jobs"
    request = {"sample_id": "glazed-bowl", "run_mode": "practice", "metadata_source": "archive"}
    assert client.get(publication + "/availability", headers=own).get_json()["data"] == {
        "ready": True, "practice_ready": False, "credential_ready": False, "demo": False,
    }
    assert client.post(url, headers=own, data=request).status_code == 503
    (tmp_path / queue.PRACTICE_HEARTBEAT).touch()
    assert client.get(publication + "/availability", headers=own).get_json()["data"]["practice_ready"]
    assert client.get(publication + "/availability", headers=demo).get_json()["data"]["practice_ready"] is False
    assert client.post(url, headers=demo, data=request).status_code == 403
    assert client.post(url, headers=other, data=request).status_code == 403
    assert client.post(url, data=request).status_code == 401
    assert client.post(url, headers=own, data={**request, "run_mode": "sandbox"}).status_code == 409
    assert client.post(url, headers=own, data={**request, "sample_id": "three-model-batch"}).status_code == 400
    assert client.post(url, headers=own, data={**request, "title": "New title"}).status_code == 400
    assert client.post(url, headers=own, data={"run_mode": "practice", "archive": (io.BytesIO(b"not a sample"), "test.zip")}).status_code == 400
    assert client.post(url, headers=own, data={**request, "msf": (io.BytesIO(b"new data"), "test.csv")}).status_code == 400

    def forbidden(*_args, **_kwargs):
        pytest.fail("A practice worker contacted Sandbox or read depositor credentials")

    def invalid_credential(*_args):
        raise InvalidToken

    monkeypatch.setattr(model_publication_routes, "sandbox_token", invalid_credential)
    monkeypatch.setattr(worker, "DraftClient", forbidden)
    monkeypatch.setattr(worker, "sandbox_token", forbidden)
    independent = client.get(publication + "/availability", headers=own).get_json()["data"]
    assert independent["practice_ready"] is True and independent["credential_ready"] is False
    initial = client.post(url, headers={**own, "Idempotency-Key": "try-one"}, data=request)
    assert initial.status_code == 202
    job = initial.get_json()["data"]["job"]
    assert job["sample_id"] == "glazed-bowl" and job["run_mode"] == "practice"
    assert client.post(url, headers={**own, "Idempotency-Key": "try-one"}, data=request).status_code == 200
    assert client.get(f"{url}/{job['id']}", headers=other).status_code == 404
    stored = queue.claim(tmp_path)
    assert stored["id"] == job["id"]
    params = json.loads(stored["input_json"])
    assert params["sample_id"] is None and params["practice_sample_id"] == "glazed-bowl"
    worker.process(app, tmp_path, stored)
    result = client.get(f"{url}/{job['id']}", headers=own).get_json()["data"]["job"]
    assert result["status"] == "completed" and result["run_mode"] == "practice" and "draft" not in result
    assert {repair["kind"] for repair in result["repairs"]} == {"relinked", "material_fallback"}
    assert {file["name"] for file in result["files"]} == {"model.glb", "preview.png", "metadata.json", "metadata.csv"}

    with app.app_context():
        resumed = {"Authorization": "Bearer " + create_access_token(identity=str(learner_id))}
    output = f"{url}/{job['id']}/files/"
    model = client.get(output + "model.glb", headers=resumed)
    assert model.status_code == 200 and model.data.startswith(b"glTF") and "no-store" in model.headers["Cache-Control"]
    glb_json_size, glb_json_type = struct.unpack_from("<II", model.data, 12)
    assert glb_json_type == 0x4E4F534A
    glb = json.loads(model.data[20:20 + glb_json_size])
    assert len(glb["images"]) == 1 and "bufferView" in glb["images"][0] and "uri" not in glb["images"][0]
    assert client.get(output + "preview.png", headers=own).data.startswith(b"\x89PNG\r\n\x1a\n")
    metadata = client.get(output + "metadata.json", headers=own)
    assert json.loads(metadata.data) == result["metadata"]
    assert result["metadata"]["title"] == "Glazed Bowl" and result["metadata"]["license"] == "cc0-1.0"
    spreadsheet = client.get(output + "metadata.csv", headers=own)
    assert b"Glazed Bowl" in spreadsheet.data and b"filename" in spreadsheet.data
    assert client.get(output + "model.glb", headers=other).status_code == 404
    assert client.get(output + "metadata.csv").status_code == 401
    assert client.get(f"{url}?run_mode=practice", headers=own).get_json()["data"]["jobs"][0]["id"] == job["id"]
    assert client.get(f"{url}?run_mode=sandbox", headers=own).get_json()["data"]["jobs"] == []
    monkeypatch.setattr(model_publication_routes, "sandbox_token", lambda *_: "separate-sandbox-token")
    assert client.post(url, headers={**own, "Idempotency-Key": "try-one"}, data={**request, "run_mode": "sandbox"}).status_code == 409
    sandbox_id, _ = queue.reserve(tmp_path, user_id=learner_id, sign_in="older-sign-in", request_key="legacy",
                                  demo_window=0, parameters={"sample_id": "glazed-bowl"})
    queue.enqueue(tmp_path, sandbox_id)
    assert client.get(f"{url}?run_mode=sandbox", headers=own).get_json()["data"]["jobs"][0]["run_mode"] == "sandbox"
    repeat = client.post(url, headers=own, data=request)
    assert repeat.status_code == 202 and repeat.get_json()["data"]["job"]["id"] != job["id"]
