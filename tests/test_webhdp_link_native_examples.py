"""Real uploads, durable queue, native engine, and artifact integration checks.

No HTTP/computation/adapter mocks. Configure the installed HMSM source/runtime
using WEBHDP_LINK_HMSM_SOURCE and WEBHDP_LINK_HMSM_PYTHON to run this suite.
"""

from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

from flask import Flask
import pytest
from werkzeug.datastructures import FileStorage

from database.database import db
from database.models import PipelineRun, PipelineRunStatus, Session, User, UserRole
from database.webhdp_link_models import LinkArtifact, LinkRun, LinkToken
from external_code.webhdp_link_examples.seed import seed
from services.native_pipeline_system import NativePipelineSystemService
from services import webhdp_link_service as link
from services import webhdp_link_worker as worker


FIXTURES = Path(__file__).resolve().parents[1] / "external_code/webhdp_link_examples/fixtures"


@pytest.fixture
def system(tmp_path):
    pytest.importorskip("PIL")
    source = os.environ.get("WEBHDP_LINK_HMSM_SOURCE")
    python = os.environ.get("WEBHDP_LINK_HMSM_PYTHON")
    if not source or not python:
        pytest.skip("Set WEBHDP_LINK_HMSM_SOURCE and WEBHDP_LINK_HMSM_PYTHON for real native examples.")
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/webhdp.sqlite",
        SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY="local-integration-only",
        WEBHDP_LINK_STORAGE_PATH=str(tmp_path / "storage"), WEBHDP_LINK_PUBLIC_BASE_URL="http://127.0.0.1:5299",
        WEBHDP_DEPLOYMENT_MODE="local", WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True,
        ENABLE_RENDERER=False, ENABLE_USDZ_CONVERSION=False, ENABLE_METIS_VALIDATION=False)
    db.init_app(app)
    service = NativePipelineSystemService()
    app.native_pipeline_service = service
    with app.test_request_context("/"):
        db.create_all()
        user = User(email="link-native@example.test", role=UserRole.ADMIN, is_verified=True, token_version=0)
        user.set_password("local-integration-only")
        db.session.add(user); db.session.commit()
        for payload in seed(service, hmsm_source=source, hmsm_python=python):
            link.save_publication(payload)
        client = link.save_client({"id": "native-examples", "name": "Native integration suite",
            "origins": ["http://127.0.0.1:5300"], "redirect_uris": ["http://127.0.0.1:5300/callback"],
            "pipeline_ids": ["link-photo-preparation", "link-piano-roll", "link-model-deposit"], "max_concurrent_runs": 1})
        credentials = link.issue_token(client, user, service=True)
        token = db.session.get(LinkToken, credentials["token_id"])
        yield {"app": app, "service": service, "client": client, "user": user, "token": token, "root": tmp_path}
        db.session.remove()
        db.drop_all()


def upload(system, name, data=None):
    source = data if data is not None else (FIXTURES / name).read_bytes()
    return link.accept_upload(FileStorage(stream=io.BytesIO(source), filename=name), system["token"], system["client"])


def submit(system, publication, names, parameters=None):
    uploads = [upload(system, name) for name in names]
    payload = {"pipeline_id": publication, "inputs": [item.id for item in uploads], "parameters": parameters or {}}
    key = str(uuid4())
    run, reused = link.submit_run(payload, system["token"], system["client"], key)
    assert reused is False and run.status == "queued"
    duplicate, reused = link.submit_run(payload, system["token"], system["client"], key)
    assert reused is True and duplicate.id == run.id
    return run


def process(run):
    assert worker.process_next() is True
    db.session.expire_all()
    result = db.session.get(LinkRun, run.id)
    native = db.session.get(PipelineRun, result.native_run_id) if result.native_run_id else None
    assert result.status == "succeeded", (result.error_code, native.error_message if native else None)
    assert native.status == PipelineRunStatus.COMPLETED
    session = db.session.get(Session, result.session_id)
    assert session.origin_type == "webhdp_link" and session.sharing_scope == "private"
    assert session.status == "completed"
    artifacts = LinkArtifact.query.filter_by(run_id=result.id).all()
    paths = {artifact.name: link.artifact_path(result, artifact) for artifact in artifacts}
    for artifact in artifacts:
        assert hashlib.sha256(paths[artifact.name].read_bytes()).hexdigest() == artifact.sha256
        assert paths[artifact.name].stat().st_size == artifact.size
    public = link.serialize_run(result)
    assert public["progress"]["completed"] == public["progress"]["total"]
    assert str(Path(session.session_dir)) not in json.dumps(public)
    return result, native, paths


def test_three_apps_process_real_uploaded_data_through_native_engine(system):
    photo, photo_native, photos = process(submit(system, "link-photo-preparation", ["photo-1.jpg", "photo-2.jpg", "photo-3.jpg"], {"max_side": 128}))
    report = json.loads(photos["photo-report.json"].read_text())
    assert report["image_count"] == 3 and report["photogrammetry_executed"] is False
    from PIL import Image
    with Image.open(photos["contact-sheet.jpg"]) as image:
        assert image.size == (432, 170)  # proves external max_side reached the component
    assert len(photo_native.step_runs) == 1

    piano, piano_native, music = process(submit(system, "link-piano-roll", ["piano-roll.png"], {"roll_speed": 9}))
    report = json.loads(music["piano-report.json"].read_text())
    assert report["note_count"] == 7 and report["roll_speed_fpm"] == 9
    assert [note["pitch"] for note in report["notes"]] == [60, 64, 67, 64, 60, 55, 48]
    assert music["result.mid"].read_bytes()[:4] == b"MThd"
    assert len(piano_native.step_runs) == 1

    model, model_native, models = process(submit(system, "link-model-deposit", ["tetrahedron.obj"], {"title": "Native test tetrahedron", "target_extent": 4}))
    report = json.loads(models["mesh-report.json"].read_text())
    assert report["title"] == "Native test tetrahedron" and report["transform"]["uniform_scale"] == 2
    assert report["checks"]["closed_consistent_edge_topology"] is True
    assert models["normalized.glb"].read_bytes()[:4] == b"glTF"
    assert len(model_native.step_runs) == 1
    assert worker.process_next() is False
    assert len({photo.session_id, piano.session_id, model.session_id}) == 3


def _register_chain(system):
    # A new administrator-supplied processor with two different operations.
    # Step two must read exactly step one's output and cannot fall back to the upload.
    script = system["root"] / "chain_processor.py"
    script.write_text('''import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input-file');p.add_argument('--operation');p.add_argument('--factor',type=int,default=1)
a=p.parse_args();source=Path(a.input_file);raw=source.read_bytes();value=json.loads(raw)
if a.operation=='multiply':
    result={'product':value['value']*a.factor,'source_sha256':hashlib.sha256(raw).hexdigest()}
elif a.operation=='summarize':
    result={'verified_product':value['product'],'upstream_sha256':hashlib.sha256(raw).hexdigest(),'source_name':source.name}
else:raise ValueError('Unknown operation')
Path('result.json').write_text(json.dumps(result))
''')
    manifest = {"metadata": {"name": "link_integration_arithmetic", "label": "Arithmetic evidence", "version": "1.0.0"},
        "inputs": [{"name": "input_file", "type": "file_path", "required": True}],
        "outputs": [{"name": "result_file", "type": "file_path", "required": True}],
        "parameter_groups": [{"title": "Operation", "parameters": [{"name": "operation", "type": "string", "default": "multiply"}, {"name": "factor", "type": "integer", "default": 1}]}],
        "execution": {"profiles": [{"id": "local", "adapter": "local_cli", "entrypoint": [sys.executable, str(script)], "output_collection": [{"name": "result_file", "path": "result.json"}]}]}}
    system["service"].import_component_from_manifest(manifest)
    definition = {"identifier": "a_new_two_stage_pipeline", "name": "Custom chain", "version": "1.0.0", "steps": [
        {"id": "multiply", "component_ref": "link_integration_arithmetic", "execution_profile_ref": "local", "scope": "record", "parameters": {"operation": "multiply"}, "input_bindings": [{"kind": "input", "target": "input_file", "type": "pipeline_source_file"}]},
        {"id": "summarize", "component_ref": "link_integration_arithmetic", "execution_profile_ref": "local", "scope": "record", "parameters": {"operation": "summarize"}, "input_bindings": [{"kind": "input", "target": "input_file", "type": "artifact_file", "source_step": "multiply", "source_output": "result_file"}]},
    ]}
    system["service"].create_pipeline_version_from_config(definition["identifier"], definition)
    publication = link.save_publication({"id": "extension-proof", "name": "Custom two-stage processing", "pipeline_identifier": definition["identifier"], "pipeline_version": "1.0.0",
        "input": {"min_files": 1, "max_files": 3, "extensions": [".json"]}, "execution_mode": "record",
        "parameters": {"multiplier": {"step_id": "multiply", "parameter": "factor", "type": "integer", "minimum": 1, "maximum": 20, "default": 3}}})
    config = link.client_config(system["client"])
    link.save_client({"pipeline_ids": config["pipeline_ids"] + [publication.id]}, existing=system["client"])
    credentials = link.issue_token(system["client"], system["user"], service=True)
    system["token"] = db.session.get(LinkToken, credentials["token_id"])
    return definition


def test_custom_two_step_pipeline_binds_real_output_and_pins_queued_version(system):
    definition = _register_chain(system)
    source = upload(system, "input.json", b'{"value":7}')
    run, _ = link.submit_run({"pipeline_id": "extension-proof", "inputs": [source.id], "parameters": {"multiplier": 6}}, system["token"], system["client"], str(uuid4()))
    queued_version = run.pipeline_version_id
    # An operator subsequently changes the active version; this accepted run must
    # still execute its original version, with the original artifact binding.
    next_definition = deepcopy(definition)
    next_definition["version"] = "1.0.1"
    next_definition["steps"][1]["parameters"]["operation"] = "unavailable"
    system["service"].create_pipeline_version_from_config(definition["identifier"], next_definition)
    assert worker.process_next() is True
    db.session.expire_all()
    row = db.session.get(LinkRun, run.id)
    native = db.session.get(PipelineRun, row.native_run_id)
    assert row.status == "succeeded", native.error_message if native else row.error_code
    assert native.pipeline_version_id == queued_version
    assert len(native.step_runs) == 2
    artifacts = LinkArtifact.query.filter_by(run_id=row.id).all()
    assert len(artifacts) == 2
    paths = [link.artifact_path(row, artifact) for artifact in artifacts]
    first = next(path for path in paths if "link-step-multiply" in str(path))
    second = next(path for path in paths if "link-step-summarize" in str(path))
    assert first != second and first.name == second.name == "result.json"
    assert json.loads(first.read_text())["product"] == 42
    result = json.loads(second.read_text())
    assert result["verified_product"] == 42
    assert result["upstream_sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert link.serialize_run(row)["progress"] == {"completed": 2, "total": 2, "phase": "completed"}


def test_revoked_job_and_tampered_upload_never_execute(system):
    run = submit(system, "link-model-deposit", ["tetrahedron.obj"])
    system["token"].revoked = True; db.session.commit()
    assert worker.process_next() is False
    db.session.refresh(run)
    assert run.status == "failed" and run.error_code == "authorization_revoked"
    assert run.native_run_id is None
    system["token"].revoked = False; db.session.commit()
    source = upload(system, "tetrahedron.obj")
    run, _ = link.submit_run({"pipeline_id": "link-model-deposit", "inputs": [source.id]}, system["token"], system["client"], str(uuid4()))
    link.upload_path(source).write_bytes(b"changed after acceptance")
    assert worker.process_next() is True
    db.session.refresh(run)
    assert run.status == "failed" and run.native_run_id is None
    assert LinkArtifact.query.filter_by(run_id=run.id).count() == 0


def test_expired_token_does_not_discard_already_authorized_queued_work(system):
    run = submit(system, "link-model-deposit", ["tetrahedron.obj"])
    system["token"].expires_at = link.now() - timedelta(seconds=1); db.session.commit()
    completed, _, _ = process(run)
    assert completed.status == "succeeded"


def _chain_run(system):
    _register_chain(system)
    source = upload(system, "input.json", b'{"value":7}')
    run, _ = link.submit_run({"pipeline_id": "extension-proof", "inputs": [source.id]}, system["token"], system["client"], str(uuid4()))
    return run


def test_symlink_output_is_never_published_and_stops_downstream_step(system):
    run = _chain_run(system)
    private = system["root"] / "private.json"
    private.write_text('{"private":"not an artifact"}')
    script = system["root"] / "chain_processor.py"
    script.write_text("from pathlib import Path\nPath('result.json').symlink_to(" + repr(str(private)) + ")\n")
    assert worker.process_next() is True
    db.session.refresh(run)
    assert run.status == "failed"
    assert LinkArtifact.query.filter_by(run_id=run.id).count() == 0
    native = db.session.get(PipelineRun, run.native_run_id)
    assert len(native.step_runs) == 1
    assert "outside the private output" in native.error_message
    assert private.read_text() == '{"private":"not an artifact"}'


def test_cancel_while_first_component_finishes_prevents_second_component(system):
    run = _chain_run(system)
    marker, release = system["root"] / "first-stage-ready", system["root"] / "finish-first-stage"
    script = system["root"] / "chain_processor.py"
    script.write_text(script.read_text() + "\nif a.operation=='multiply':\n"
        + "    import time\n"
        + "    Path(" + repr(str(marker)) + ").write_text('ready')\n"
        + "    deadline=time.monotonic()+10\n"
        + "    while not Path(" + repr(str(release)) + ").exists():\n"
        + "        if time.monotonic()>deadline:raise RuntimeError('cancel test did not release')\n"
        + "        time.sleep(.01)\n")
    failures = []
    run_id = run.id
    def cancel_after_stage():
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        try:
            assert marker.exists(), "first component never reached completion marker"
            with system["app"].app_context():
                worker_run = db.session.get(LinkRun, run_id)
                link.cancel_run(worker_run)
        except Exception as exc:
            failures.append(exc)
        finally:
            release.write_text("finish")
    thread = threading.Thread(target=cancel_after_stage, daemon=True)
    thread.start()
    assert worker.process_next() is True
    thread.join(timeout=12)
    assert not thread.is_alive() and failures == []
    db.session.refresh(run)
    assert run.status == "cancelled" and run.cancel_requested is True
    native = db.session.get(PipelineRun, run.native_run_id)
    assert len(native.step_runs) == 1
    assert LinkArtifact.query.filter_by(run_id=run.id).count() == 0


def test_interrupted_worker_claim_is_failed_without_replaying_component(system):
    run = _chain_run(system)
    claimed = worker.claim_next()
    assert claimed == run.id
    run.heartbeat_at = link.now() - timedelta(seconds=500)
    db.session.commit()
    worker.recover_interrupted()
    db.session.refresh(run)
    assert run.status == "failed" and run.error_code == "interrupted"
    assert worker.process_next() is False
    assert run.native_run_id is None
    assert not (link.storage_root() / "runs" / run.id).exists()


def test_undeclared_large_output_counts_toward_quota_and_is_cleaned_up(system):
    run = _chain_run(system)
    link.save_client({"max_storage_bytes": 8 * 1024 * 1024}, existing=system["client"])
    script = system["root"] / "chain_processor.py"
    script.write_text(script.read_text() + "\nif a.operation=='multiply':\n    Path('undeclared-intermediate.bin').write_bytes(b'x'*(16*1024*1024))\n")
    assert worker.process_next() is True
    db.session.refresh(run)
    assert run.status == "failed" and run.error_code == "storage_quota_exceeded"
    assert LinkArtifact.query.filter_by(run_id=run.id).count() == 0
    assert not (link.storage_root() / "runs" / run.id / "outputs").exists()
    assert link.storage_used(system["client"].id) < 8 * 1024 * 1024
