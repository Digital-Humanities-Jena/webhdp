"""Sandbox-only transport, fixity, retry, native schema and secret isolation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

from flask import Flask
import pytest
import requests
import yaml

from database.database import db
from exceptions import FileProcessingError
from external_code.webhdp_link_examples.runner import mesh_package
from external_code.webhdp_link_zenodo import runner, seed
from services import webhdp_link_secrets as secrets
from services.native_pipeline_system import NativePipelineSystemService
from services import webhdp_link_service as link
from services import webhdp_link_worker as worker


class Response:
    def __init__(self, value=None, *, status=200, content=b""):
        self.status_code, self.value, self.content = status, value, content
        self.closed = False

    def json(self):
        return deepcopy(self.value)

    def iter_content(self, size):
        yield self.content

    def close(self):
        self.closed = True


class Sandbox:
    def __init__(self):
        self.calls, self.files = [], {}
        self.bucket = runner.SANDBOX + "/api/files/bucket-123"
        self.submitted, self.corrupt_download, self.corrupt_upload = False, False, False
        self.create_failure = None

    def draft(self):
        return {"id": 123, "submitted": self.submitted, "state": "unsubmitted", "links": {"bucket": self.bucket},
                "files": [{"filename": name, "filesize": len(content), "checksum": hashlib.md5(content).hexdigest()}
                          for name, content in self.files.items()]}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["Authorization"] == "Bearer private-test-token"
        if method == "POST":
            if self.create_failure:
                raise self.create_failure
            return Response(self.draft(), status=201)
        if url == runner.API + "/123":
            return Response(self.draft())
        name = unquote(url.rsplit("/", 1)[-1])
        if method == "PUT":
            self.files[name] = content = kwargs["data"].read()
            return Response({"size": len(content), "checksum": "md5:" + ("0" * 32 if self.corrupt_upload else hashlib.md5(content).hexdigest())}, status=201)
        return Response(content=b"bad" if self.corrupt_download else self.files[name])


@pytest.fixture
def inputs(tmp_path):
    source = Path(__file__).resolve().parents[1] / "external_code/webhdp_link_examples/fixtures/tetrahedron.obj"
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    mesh_package(source, prepared, title="Sandbox test model")
    return {"metadata_file": prepared / "zenodo-metadata.json", "model_file": prepared / "normalized.glb",
            "mesh_report": prepared / "mesh-report.json", "package_file": prepared / "model-package.zip",
            "source": source, "creator_name": "Validation, WebHDP-Link", "output_directory": tmp_path / "deposit",
            "token": "private-test-token"}


def test_uploads_real_prepared_model_and_verifies_every_remote_byte(inputs):
    sandbox = Sandbox()
    result = runner.create_sandbox_draft(**inputs, session=sandbox)
    assert result["deposition_id"] == 123
    assert result["submitted"] is False and result["publication_attempted"] is False
    assert result["publication_status"] == "unpublished_draft"
    assert len(result["files"]) == 5
    assert all(hashlib.sha256(sandbox.files[item["name"]]).hexdigest() == item["sha256"] for item in result["files"])
    assert len([call for call in sandbox.calls if call[0] == "POST"]) == 1
    assert len([call for call in sandbox.calls if call[0] == "PUT"]) == 5
    assert all(url.startswith(runner.SANDBOX + "/api/") and "publish" not in url and "access_token" not in url for _, url, _ in sandbox.calls)
    receipt = (inputs["output_directory"] / "zenodo-sandbox-receipt.json").read_text()
    checkpoint = (inputs["output_directory"] / "sandbox-operation-state.json").read_text()
    assert inputs["token"] not in receipt + checkpoint
    assert str(inputs["source"]) not in receipt + checkpoint
    assert sandbox.trust_env is False


def test_confirmed_retry_reuses_draft_and_reverifies_without_duplicate_upload(inputs):
    sandbox = Sandbox()
    runner.create_sandbox_draft(**inputs, session=sandbox)
    runner.create_sandbox_draft(**inputs, session=sandbox)
    assert len([call for call in sandbox.calls if call[0] == "POST"]) == 1
    assert len([call for call in sandbox.calls if call[0] == "PUT"]) == 5
    assert len([call for call in sandbox.calls if call[0] == "GET" and "/api/files/" in call[1]]) == 10


def test_uncertain_create_is_not_automatically_repeated(inputs):
    sandbox = Sandbox()
    sandbox.create_failure = requests.Timeout("server may have created a draft")
    with pytest.raises(RuntimeError, match="could not confirm"):
        runner.create_sandbox_draft(**inputs, session=sandbox)
    sandbox.create_failure = None
    with pytest.raises(RuntimeError, match="Operator reconciliation"):
        runner.create_sandbox_draft(**inputs, session=sandbox)
    assert len(sandbox.calls) == 1


@pytest.mark.parametrize("destination", ["https://zenodo.org/api/files/bucket-123", "https://sandbox.zenodo.org.evil.test/api/files/bucket-123", "https://sandbox.zenodo.org/api/files/bucket-123?access_token=anything"])
def test_rejects_untrusted_storage_destination_before_upload(inputs, destination):
    sandbox = Sandbox()
    sandbox.bucket = destination
    with pytest.raises(RuntimeError, match="unexpected storage"):
        runner.create_sandbox_draft(**inputs, session=sandbox)
    assert [call[0] for call in sandbox.calls] == ["POST"]


def test_submitted_resource_is_never_modified(inputs):
    sandbox = Sandbox()
    sandbox.submitted = True
    with pytest.raises(RuntimeError, match="not an unpublished draft"):
        runner.create_sandbox_draft(**inputs, session=sandbox)
    assert [call[0] for call in sandbox.calls] == ["POST"]


@pytest.mark.parametrize("fault", ["corrupt_upload", "corrupt_download"])
def test_checksum_failure_never_creates_success_receipt(inputs, fault):
    sandbox = Sandbox()
    setattr(sandbox, fault, True)
    with pytest.raises(RuntimeError, match="checksum|SHA-256"):
        runner.create_sandbox_draft(**inputs, session=sandbox)
    assert not (inputs["output_directory"] / "zenodo-sandbox-receipt.json").exists()


def test_resume_rejects_changed_and_unexpected_remote_files(inputs):
    sandbox = Sandbox()
    runner.create_sandbox_draft(**inputs, session=sandbox)
    sandbox.files["extra.txt"] = b"unexpected"
    with pytest.raises(RuntimeError, match="unexpected files"):
        runner.create_sandbox_draft(**inputs, session=sandbox)
    del sandbox.files["extra.txt"]
    sandbox.files["normalized.glb"] = b"altered"
    with pytest.raises(RuntimeError, match="will not be overwritten"):
        runner.create_sandbox_draft(**inputs, session=sandbox)


def test_metadata_cannot_supply_credentials_or_custom_endpoints(inputs):
    document = json.loads(inputs["metadata_file"].read_text())
    document["metadata"]["access_token"] = "must-not-be-forwarded"
    inputs["metadata_file"].write_text(json.dumps(document))
    sandbox = Sandbox()
    with pytest.raises(ValueError, match="only dataset"):
        runner.create_sandbox_draft(**inputs, session=sandbox)
    assert sandbox.calls == []


@pytest.mark.parametrize("method,url", [("POST", runner.API + "/123/actions/publish"), ("POST", "https://zenodo.org/api/deposit/depositions"), ("DELETE", runner.API + "/123"), ("GET", runner.API + "/123?access_token=token")])
def test_transport_has_no_publish_production_delete_or_query_token_surface(method, url):
    sandbox = Sandbox()
    with pytest.raises(RuntimeError, match="Only sandbox"):
        runner.SandboxClient("private-test-token", sandbox).request(method, url, expected={200})
    assert sandbox.calls == []


def trusted_request():
    manifest, _, _ = seed.definitions()
    return SimpleNamespace(metadata={"component_manifest": manifest}, profile=deepcopy(manifest["execution"]["profiles"][0]), environment={})


def test_secret_resolves_current_users_active_sandbox_without_mutating_request(monkeypatch):
    calls = []
    service = SimpleNamespace(get_active_credential=lambda user, env: calls.append((user, env)) or SimpleNamespace(environment="sandbox"), decrypt_value=lambda credential: "private-test-token")
    monkeypatch.setattr(secrets, "ZenodoCredentialService", lambda: service)
    request = trusted_request()
    original = deepcopy(request)
    assert secrets.component_environment(request, 7) == {runner.TOKEN_ENV: "private-test-token"}
    assert calls == [(7, "sandbox")]
    assert request == original


@pytest.mark.parametrize("change", ["name", "version", "runner", "hash", "interpreter", "adapter"])
def test_unapproved_component_cannot_resolve_credential(monkeypatch, change):
    monkeypatch.setattr(secrets, "ZenodoCredentialService", lambda: pytest.fail("Credential lookup must not occur"))
    request = trusted_request()
    if change in {"name", "version"}:
        request.metadata["component_manifest"]["metadata"][change] = "unapproved"
    elif change == "adapter":
        request.profile["adapter"] = "ssh_command"
    else:
        request.profile["entrypoint"][{"runner": 1, "hash": 3, "interpreter": 0}[change]] = "/tmp/unapproved"
    if change == "name":
        assert secrets.component_environment(request, 7) == {}
    else:
        with pytest.raises(FileProcessingError, match="approved installed component"):
            secrets.component_environment(request, 7)


@pytest.mark.parametrize("credential", [None, SimpleNamespace(environment="production")])
def test_missing_or_wrong_environment_credential_fails_closed(monkeypatch, credential):
    service = SimpleNamespace(get_active_credential=lambda user, env: credential, decrypt_value=lambda credential: pytest.fail("No secret decryption"))
    monkeypatch.setattr(secrets, "ZenodoCredentialService", lambda: service)
    with pytest.raises(FileProcessingError, match="Sandbox credential"):
        secrets.component_environment(trusted_request(), 7)


@pytest.mark.parametrize("raises", [False, True])
def test_worker_injects_only_during_delegate_call_and_restores_environment(monkeypatch, tmp_path, raises):
    monkeypatch.setattr(worker, "check_run", lambda run_id: None)
    monkeypatch.setattr(worker, "db", SimpleNamespace(session=SimpleNamespace(get=lambda model, identity: SimpleNamespace(user_id=7))))
    calls = []
    credential_service = SimpleNamespace(get_active_credential=lambda user, env: calls.append((user, env)) or SimpleNamespace(environment="sandbox"), decrypt_value=lambda credential: "private-test-token")
    monkeypatch.setattr(secrets, "ZenodoCredentialService", lambda: credential_service)
    request = trusted_request()
    request.step_id, request.workdir = "deposit", str(tmp_path / "outputs")
    request.inputs, request.parameters, request.environment = {}, {}, {"EXISTING_CONFIG": "retained"}
    original_environment = request.environment
    def execute(received):
        assert received.environment == {"EXISTING_CONFIG": "retained", runner.TOKEN_ENV: "private-test-token"}
        assert "private-test-token" not in json.dumps(received.metadata)
        if raises:
            raise RuntimeError("deliberate delegate error")
        receipt = Path(received.workdir) / "zenodo-sandbox-receipt.json"
        receipt.write_text("{}")
        return {"success": True, "outputs": {"sandbox_receipt": str(receipt)}, "artifacts": [{"path": str(receipt)}]}
    guarded = worker.GuardedAdapter(SimpleNamespace(execute=execute), "run-id", tmp_path, 1800)
    if raises:
        with pytest.raises(RuntimeError, match="deliberate delegate"):
            guarded.execute(request)
    else:
        result = guarded.execute(request)
        assert "private-test-token" not in json.dumps(result)
    assert request.environment is original_environment
    assert runner.TOKEN_ENV not in request.environment
    assert calls == [(7, "sandbox")]


def test_native_pipeline_installs_artifact_bindings_and_safe_public_parameters(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-only", SQLALCHEMY_DATABASE_URI="sqlite://", SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      WEBHDP_DEPLOYMENT_MODE="local", WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()
    with app.app_context():
        db.create_all()
        try:
            root = Path(__file__).resolve().parents[1] / "external_code/webhdp_link_examples"
            mesh_manifest = yaml.safe_load((root / "link_mesh_packager/component.yaml").read_text())
            app.native_pipeline_service.import_component_from_manifest(mesh_manifest)
            publication = seed.seed(app.native_pipeline_service)
            saved = link.save_publication(publication)
            assert saved.id == "link-model-sandbox-draft"
            descriptor = link.serialize_publication(saved)
            assert len(descriptor["structure"]) == 2
            assert set(descriptor["parameter_schema"]["properties"]) == {"title", "target_extent", "creator_name"}
            assert "token" not in json.dumps(descriptor).lower()
        finally:
            db.session.remove()
            db.drop_all()
