"""The independent Sandbox verifier performs only authenticated fixed-origin GETs."""
from copy import deepcopy
import hashlib
import json

import pytest
import requests

from scripts import verify_webhdp_link_sandbox as verifier


TOKEN = "sandbox-private-test-key"
CONTENTS = {name: (name + "-verified-bytes").encode() for name in ["source.obj", "normalized.glb", "mesh-report.json", "zenodo-metadata.json", "model-package.zip"]}


def receipt():
    return {"deposition_id": 123, "draft_url": "https://sandbox.zenodo.org/uploads/123", "operation": "zenodo-sandbox-draft",
            "environment": "sandbox", "submitted": False, "state": "unsubmitted", "publication_attempted": False,
            "publication_status": "unpublished_draft", "files": [{"name": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()} for name, content in CONTENTS.items()]}


class Response:
    def __init__(self, *, payload=None, body=b"", status=200):
        self.payload, self.body, self.status_code, self.closed = payload, body, status, False

    def json(self):
        return deepcopy(self.payload)

    def iter_content(self, size):
        for offset in range(0, len(self.body), 5):
            yield self.body[offset:offset + 5]

    def close(self):
        self.closed = True


class Transport:
    def __init__(self):
        self.calls, self.responses, self.reads = [], [], 0
        self.files = dict(CONTENTS)
        self.bucket = "https://sandbox.zenodo.org/api/files/bucket-123"
        self.submitted, self.publish_on_final_read = False, False
        self.status = 200
        self.remote_files = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert method == "GET", "Verifier attempted a mutation"
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["Authorization"] == "Bearer " + TOKEN
        if url == verifier.API + "/123":
            self.reads += 1
            payload = {"id": 123, "submitted": self.submitted or (self.publish_on_final_read and self.reads > 1), "state": "unsubmitted",
                       "links": {"bucket": self.bucket}, "files": self.remote_files if self.remote_files is not None else [{"filename": name, "filesize": len(body)} for name, body in CONTENTS.items()]}
            result = Response(payload=payload, status=self.status)
        else:
            result = Response(body=self.files[url.rsplit("/", 1)[1]], status=self.status)
        self.responses.append(result)
        return result


def test_get_only_verification_streams_every_file_and_rechecks_unsubmitted_state():
    transport = Transport()
    proof = verifier.verify(receipt(), TOKEN, session=transport)
    assert proof["success"] is True and proof["submitted"] is False and proof["file_count"] == 5
    assert transport.reads == 2 and len(transport.calls) == 7
    assert all(response.closed for response in transport.responses)
    assert all(method == "GET" and url.startswith(verifier.SANDBOX + "/api/") and "publish" not in url for method, url, _ in transport.calls)
    assert all(item["sha256"] == hashlib.sha256(CONTENTS[item["name"]]).hexdigest() for item in proof["files"])
    assert TOKEN not in json.dumps(proof) and transport.trust_env is False


@pytest.mark.parametrize("patch", [{"draft_url": "https://zenodo.org/uploads/123"}, {"draft_url": "https://sandbox.zenodo.org/uploads/123?token=unsafe"}, {"submitted": True}, {"environment": "production"}, {"publication_attempted": True}])
def test_invalid_receipt_never_reaches_network(patch):
    transport = Transport()
    with pytest.raises(ValueError):
        verifier.verify({**receipt(), **patch}, TOKEN, session=transport)
    assert transport.calls == []


@pytest.mark.parametrize("name", ["../secret", "file/secret", "%2e%2e", "https://evil.test/file"])
def test_untrusted_filenames_never_reach_network(name):
    value = receipt(); value["files"][0]["name"] = name
    transport = Transport()
    with pytest.raises(ValueError, match="safe basenames"):
        verifier.verify(value, TOKEN, session=transport)
    assert not transport.calls


@pytest.mark.parametrize("bucket", ["https://zenodo.org/api/files/bucket-123", "https://sandbox.zenodo.org.evil.test/api/files/bucket-123", "https://sandbox.zenodo.org/api/files/bucket-123?token=unsafe"])
def test_invalid_storage_destinations_stop_before_file_request(bucket):
    transport = Transport(); transport.bucket = bucket
    with pytest.raises(ValueError, match="bucket URL"):
        verifier.verify(receipt(), TOKEN, session=transport)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("mutation", ["extra", "missing", "duplicate", "wrong_size"])
def test_remote_inventory_must_match_exactly(mutation):
    transport = Transport()
    files = [{"filename": name, "filesize": len(body)} for name, body in CONTENTS.items()]
    if mutation == "extra": files.append({"filename": "extra.txt", "filesize": 1})
    elif mutation == "missing": files.pop()
    elif mutation == "duplicate": files[-1] = files[0]
    else: files[0]["filesize"] += 1
    transport.remote_files = files
    with pytest.raises(ValueError, match="remote|Remote"):
        verifier.verify(receipt(), TOKEN, session=transport)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("change", ["short", "long", "different"])
def test_streamed_size_and_sha_mismatch_cannot_produce_success(change):
    transport = Transport()
    original = transport.files["source.obj"]
    transport.files["source.obj"] = original[:-1] if change == "short" else original + b"x" if change == "long" else b"x" * len(original)
    with pytest.raises(ValueError, match="bytes"):
        verifier.verify(receipt(), TOKEN, session=transport)
    assert all(response.closed for response in transport.responses)


def test_change_to_published_state_during_verification_is_rejected():
    transport = Transport(); transport.publish_on_final_read = True
    with pytest.raises(ValueError, match="not an unsubmitted"):
        verifier.verify(receipt(), TOKEN, session=transport)
    assert transport.reads == 2


def test_redirect_is_not_followed():
    transport = Transport(); transport.status = 302
    with pytest.raises(RuntimeError, match="redirects"):
        verifier.verify(receipt(), TOKEN, session=transport)
    assert len(transport.calls) == 1 and transport.responses[0].closed


@pytest.mark.parametrize("url", [verifier.API + "/123/actions/publish", "http://sandbox.zenodo.org/api/deposit/depositions/123", verifier.API + "/123?access_token=unsafe", verifier.SANDBOX + "/api/files/bucket/.."])
def test_transport_does_not_offer_other_endpoints(url):
    transport = Transport()
    with pytest.raises(ValueError, match="GET requests"):
        verifier.ReadOnlySandbox(TOKEN, transport).get(url)
    assert not transport.calls


@pytest.mark.parametrize("array", [True, False])
def test_cli_writes_sanitized_proof_and_preserves_matching_account_observation(tmp_path, monkeypatch, capsys, array):
    value = receipt()
    receipt_path, environment, output = tmp_path / "receipt.json", tmp_path / "environment.json", tmp_path / "proof.json"
    receipt_path.write_text(json.dumps(value))
    environment.write_text(json.dumps(["ZENODO_SANDBOX_API_KEY=" + TOKEN] if array else {"ZENODO_SANDBOX_API_KEY": TOKEN}))
    output.write_text(json.dumps({"deposition_id": 123, "account_ui_observation": "Browser not signed in."}))
    monkeypatch.setattr(verifier.requests, "Session", Transport)
    assert verifier.main(["--receipt", str(receipt_path), "--environment-file", str(environment), "--output", str(output)]) == 0
    proof = json.loads(output.read_text())
    assert proof["success"] and proof["account_ui_observation"] == "Browser not signed in."
    assert proof["receipt_sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err + output.read_text()


def test_cli_transport_failure_is_sanitized_and_keeps_previous_proof(tmp_path, monkeypatch, capsys):
    receipt_path, environment, output = tmp_path / "receipt.json", tmp_path / "environment.json", tmp_path / "proof.json"
    receipt_path.write_text(json.dumps(receipt())); environment.write_text(json.dumps({"ZENODO_SANDBOX_API_KEY": TOKEN}))
    original = '{"previous_evidence":"kept"}'; output.write_text(original)
    class FailingTransport(Transport):
        def request(self, *args, **kwargs):
            raise requests.ConnectionError("Sensitive exception " + TOKEN)
    monkeypatch.setattr(verifier.requests, "Session", FailingTransport)
    assert verifier.main(["--receipt", str(receipt_path), "--environment-file", str(environment), "--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err
    assert output.read_text() == original
