"""Create and verify an UNPUBLISHED Zenodo Sandbox draft. No publish operation exists."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit

import requests

SANDBOX = "https://sandbox.zenodo.org"
API = SANDBOX + "/api/deposit/depositions"
TOKEN_ENV = "WEBHDP_LINK_ZENODO_SANDBOX_TOKEN"
VERSION = "1.0.0"


def checksum(path, algorithm="sha256"):
    result = hashlib.new(algorithm)
    with Path(path).open("rb") as source:
        while block := source.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def safe_text(value, label, maximum=200):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a nonempty printable string of at most {maximum} characters.")
    return value.strip()


def source_file(value):
    source = Path(value)
    if not source.is_absolute() or source.resolve(strict=True) != source or not source.is_file():
        raise ValueError("Component inputs must be regular files in the managed job workspace.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", source.name):
        raise ValueError("Input filenames must contain only letters, digits, dots, underscores and hyphens.")
    if not 0 < source.stat().st_size <= 100 * 1024 * 1024:
        raise ValueError("Each sandbox demonstration artifact must contain 1 byte to 100 MiB.")
    return source


def sandbox_bucket(value):
    if not isinstance(value, str):
        raise RuntimeError("Zenodo returned no usable sandbox bucket.")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "sandbox.zenodo.org" or parsed.query or parsed.fragment
            or not re.fullmatch(r"/api/files/[A-Za-z0-9-]+/?", parsed.path)):
        raise RuntimeError("Zenodo returned an unexpected storage destination; upload stopped.")
    return value.rstrip("/")


def draft_id(payload):
    value = payload.get("id") if isinstance(payload, dict) else None
    if type(value) is not int or value <= 0:
        raise RuntimeError("Zenodo returned an invalid draft identity.")
    if payload.get("submitted") is not False or payload.get("state") not in {"unsubmitted", "inprogress"}:
        raise RuntimeError("The Zenodo resource is not an unpublished draft; processing stopped.")
    return value


def save_json(path, value):
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, indent=2, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, target)


class SandboxClient:
    """Fixed-origin transport with no redirects, query tokens or publish endpoints."""
    def __init__(self, token, session=None):
        if not isinstance(token, str) or not token.strip() or any(c.isspace() for c in token):
            raise ValueError("A centrally configured sandbox credential is required.")
        self._headers = {"Authorization": "Bearer " + token.strip(), "Accept": "application/json"}
        self._session = session or requests.Session()
        self._session.trust_env = False

    def request(self, method, url, *, expected, **kwargs):
        parsed = urlsplit(url)
        allowed = ((method == "POST" and url == API)
                   or (method == "GET" and re.fullmatch(r"/api/deposit/depositions/[1-9][0-9]*", parsed.path))
                   or (method in {"PUT", "GET"} and re.fullmatch(r"/api/files/[A-Za-z0-9-]+/[A-Za-z0-9_.%-]+", parsed.path)))
        if (parsed.scheme != "https" or parsed.netloc != "sandbox.zenodo.org" or parsed.query or parsed.fragment or not allowed):
            raise RuntimeError("Only sandbox draft creation, file upload and verification are permitted.")
        try:
            response = self._session.request(method, url, headers=self._headers, timeout=(20, 180), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise RuntimeError("Zenodo Sandbox could not confirm the request. Review the saved operation state before retrying.") from None
        if response.status_code not in expected:
            raise RuntimeError(f"Zenodo Sandbox rejected the {method} request (HTTP {response.status_code}); no publication was attempted.")
        return response

    def draft(self, identity):
        result = self.request("GET", f"{API}/{identity}", expected={200}).json()
        if draft_id(result) != identity:
            raise RuntimeError("The returned draft identity changed unexpectedly.")
        return result


def create_sandbox_draft(*, metadata_file, model_file, mesh_report, package_file, source, creator_name,
                         output_directory, token, session=None):
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata_path = source_file(metadata_file)
    if metadata_path.stat().st_size > 65536:
        raise ValueError("The metadata input exceeds 64 KiB.")
    document = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata = document.get("metadata") if isinstance(document, dict) else None
    if (not isinstance(metadata, dict) or set(metadata) - {"title", "upload_type", "description"}
            or metadata.get("upload_type") != "dataset"):
        raise ValueError("The prepared metadata must contain only dataset title, type and description.")
    metadata = {"title": safe_text(metadata.get("title"), "Dataset title"), "upload_type": "dataset",
                "description": html.escape(safe_text(metadata.get("description"), "Description", 5000)),
                "creators": [{"name": safe_text(creator_name, "Creator name")}],
                "access_right": "restricted", "access_conditions": "Unpublished WebHDP-Link Sandbox validation draft; not a scientific publication.",
                "keywords": ["webhdp-link", "sandbox-validation"]}
    paths = [source_file(item) for item in (source, model_file, mesh_report, metadata_file, package_file)]
    if len({item.name for item in paths}) != len(paths):
        raise ValueError("Draft input files must have distinct names.")
    inventory = [{"name": item.name, "size": item.stat().st_size, "sha256": checksum(item), "md5": checksum(item, "md5")} for item in paths]
    fingerprint = hashlib.sha256(json.dumps({"metadata": metadata, "files": inventory}, sort_keys=True).encode()).hexdigest()
    checkpoint = output / "sandbox-operation-state.json"
    state = json.loads(checkpoint.read_text()) if checkpoint.exists() else None
    if state and state.get("fingerprint") != fingerprint:
        raise RuntimeError("The saved draft operation belongs to different inputs; start a separate job.")
    client = SandboxClient(token, session)
    if state is None:
        state = {"schema_version": "1.0", "fingerprint": fingerprint, "phase": "creating", "environment": "sandbox"}
        save_json(checkpoint, state)
        created = client.request("POST", API, expected={201}, json={"metadata": metadata}).json()
        identity = draft_id(created)
        bucket = sandbox_bucket((created.get("links") or {}).get("bucket"))
        state.update(phase="created", deposition_id=identity, bucket=bucket)
        save_json(checkpoint, state)
    elif not state.get("deposition_id"):
        raise RuntimeError("A previous draft-creation request has no confirmed identity. Operator reconciliation is required; automatic creation is disabled.")
    identity = state["deposition_id"]
    if type(identity) is not int or identity <= 0:
        raise RuntimeError("The saved draft identity is invalid.")
    bucket = sandbox_bucket(state.get("bucket"))
    current = client.draft(identity)
    if sandbox_bucket((current.get("links") or {}).get("bucket")) != bucket:
        raise RuntimeError("The draft bucket changed unexpectedly.")
    existing = {item.get("filename"): item for item in current.get("files", [])}
    if set(existing) - {item["name"] for item in inventory}:
        raise RuntimeError("The saved draft contains unexpected files; operator review is required.")
    for path, info in zip(paths, inventory):
        url = bucket + "/" + quote(info["name"], safe="")
        if info["name"] in existing:
            previous = existing[info["name"]]
            if previous.get("checksum", "").removeprefix("md5:") != info["md5"] or previous.get("filesize") != info["size"]:
                raise RuntimeError("An existing sandbox file differs from this job; it will not be overwritten.")
        else:
            with path.open("rb") as content:
                uploaded = client.request("PUT", url, expected={200, 201}, data=content).json()
            if uploaded.get("checksum", "").removeprefix("md5:") != info["md5"] or uploaded.get("size") != info["size"]:
                raise RuntimeError("Zenodo's upload checksum or size does not match the source.")
        sha = hashlib.sha256()
        size = 0
        response = client.request("GET", url, expected={200}, stream=True)
        try:
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > info["size"]:
                    raise RuntimeError("Downloaded sandbox bytes exceed the expected file size.")
                sha.update(chunk)
        finally:
            response.close()
        if size != info["size"] or sha.hexdigest() != info["sha256"]:
            raise RuntimeError("Downloaded sandbox bytes failed SHA-256 verification.")
        state.update(phase="uploading", verified_files=[*state.get("verified_files", []), info["name"]])
        save_json(checkpoint, state)
    final = client.draft(identity)
    remote_files = {item.get("filename"): item for item in final.get("files", [])}
    if set(remote_files) != {item["name"] for item in inventory}:
        raise RuntimeError("The final sandbox draft does not contain exactly the requested files.")
    for info in inventory:
        remote = remote_files[info["name"]]
        if remote.get("checksum", "").removeprefix("md5:") != info["md5"] or remote.get("filesize") != info["size"]:
            raise RuntimeError("Final sandbox file metadata does not match the uploaded bytes.")
    receipt = {"schema_version": "1.0", "operation": "zenodo-sandbox-draft", "environment": "sandbox",
               "deposition_id": identity, "draft_url": SANDBOX + f"/uploads/{identity}", "submitted": False,
               "state": final["state"], "publication_status": "unpublished_draft", "publication_attempted": False,
               "title": metadata["title"], "creators": metadata["creators"], "files": inventory,
               "verification": "Every uploaded file was downloaded from Zenodo Sandbox and matched its local size and SHA-256.",
               "scope": "Sandbox-only unpublished draft. No production repository call or publication operation is implemented."}
    save_json(output / "zenodo-sandbox-receipt.json", receipt)
    state.update(phase="verified", verified_files=[item["name"] for item in inventory])
    save_json(checkpoint, state)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-runner-sha256", required=True)
    for name in ("metadata-file", "model-file", "mesh-report", "package-file", "source"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--creator-name", default="WebHDP-Link validation")
    args = parser.parse_args()
    try:
        if checksum(Path(__file__).resolve()) != args.expected_runner_sha256:
            raise RuntimeError("The approved component executable changed; reinstall its version before running.")
        result = create_sandbox_draft(metadata_file=args.metadata_file, model_file=args.model_file,
                                     mesh_report=args.mesh_report, package_file=args.package_file, source=args.source,
                                     creator_name=args.creator_name, output_directory=Path.cwd(), token=os.environ.get(TOKEN_ENV))
        print(json.dumps({"status": "completed", "deposition_id": result["deposition_id"], "publication_status": "unpublished_draft", "file_count": len(result["files"])}))
    except Exception as exc:
        # Never emit transport exception representations, request headers or a token.
        detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "The sandbox draft operation failed; inspect its private checkpoint."
        secret = os.environ.get(TOKEN_ENV)
        if secret:
            detail = detail.replace(secret, "[redacted]")
        print(json.dumps({"status": "failed", "error": detail}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
