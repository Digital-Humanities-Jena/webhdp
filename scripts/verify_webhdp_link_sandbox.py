#!/usr/bin/env python3
"""Independently verify an existing unpublished Sandbox draft using GET only.

The credential file is read in process memory. No creation, upload, publication,
deletion or redirect is implemented. Successful proof is written atomically;
failures leave an earlier proof file intact and return a nonzero exit status.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import quote, urlsplit

import requests

SANDBOX = "https://sandbox.zenodo.org"
API = SANDBOX + "/api/deposit/depositions"
MAX_FILE_BYTES = 100 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_document(path):
    path = Path(path)
    require(path.stat().st_size <= 2 * 1024 * 1024, "A configuration or receipt document exceeds 2 MiB.")
    return json.loads(path.read_text(encoding="utf-8"))


def load_token(path):
    value = read_document(path)
    if isinstance(value, list):
        require(all(isinstance(item, str) and "=" in item for item in value), "The environment JSON array must contain KEY=value strings.")
        value = dict(item.split("=", 1) for item in value)
    require(isinstance(value, dict), "The environment file must be a JSON object or KEY=value array.")
    token = value.get("ZENODO_SANDBOX_API_KEY")
    require(isinstance(token, str) and bool(token) and not any(character.isspace() for character in token), "A valid existing Zenodo Sandbox credential is required.")
    return token


def bucket_url(value):
    require(isinstance(value, str), "The Sandbox draft has no usable bucket.")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and parsed.netloc == "sandbox.zenodo.org" and not parsed.query and not parsed.fragment
            and bool(re.fullmatch(r"/api/files/[A-Za-z0-9-]+/?", parsed.path)), "The draft returned an invalid or non-Sandbox bucket URL.")
    return value.rstrip("/")


class ReadOnlySandbox:
    def __init__(self, token, session=None):
        require(isinstance(token, str) and bool(token) and not any(character.isspace() for character in token), "A valid Sandbox credential is required.")
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}

    def get(self, url, *, stream=False):
        parsed = urlsplit(url)
        allowed = (re.fullmatch(r"/api/deposit/depositions/[1-9][0-9]*", parsed.path)
                   or re.fullmatch(r"/api/files/[A-Za-z0-9-]+/[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", parsed.path))
        require(parsed.scheme == "https" and parsed.netloc == "sandbox.zenodo.org" and not parsed.query and not parsed.fragment and bool(allowed), "Only fixed-origin Sandbox draft/file GET requests are allowed.")
        try:
            response = self.session.request("GET", url, headers=self.headers, allow_redirects=False, timeout=(20, 180), stream=stream)
        except requests.RequestException:
            raise RuntimeError("The read-only Sandbox request failed; no remote change was attempted.") from None
        if response.status_code != 200:
            response.close()
            raise RuntimeError(f"Sandbox verification received HTTP {response.status_code}; redirects and non-success responses are refused.")
        return response

    def draft(self, identity):
        response = self.get(f"{API}/{identity}")
        try:
            return response.json()
        finally:
            response.close()


def validate_receipt(receipt):
    require(isinstance(receipt, dict), "The receipt must be an object.")
    identity = receipt.get("deposition_id")
    require(type(identity) is int and identity > 0, "The receipt has an invalid draft identity.")
    require(receipt.get("operation") == "zenodo-sandbox-draft" and receipt.get("environment") == "sandbox"
            and receipt.get("submitted") is False and receipt.get("state") == "unsubmitted"
            and receipt.get("publication_attempted") is False and receipt.get("publication_status") == "unpublished_draft", "The receipt must describe an unpublished Sandbox draft.")
    require(receipt.get("draft_url") == f"{SANDBOX}/uploads/{identity}", "The receipt draft URL does not match the fixed Sandbox destination.")
    files = receipt.get("files")
    require(isinstance(files, list) and len(files) == 5, "The model draft receipt must declare exactly five files.")
    for item in files:
        require(isinstance(item, dict), "Receipt files must be objects.")
        name = item.get("name")
        require(isinstance(name, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", name)), "Receipt filenames must be simple safe basenames.")
        require(type(item.get("size")) is int and 0 < item["size"] <= MAX_FILE_BYTES, "A receipt file size is outside the component's 1-byte to 100-MiB limit.")
        require(isinstance(item.get("sha256"), str) and bool(re.fullmatch(r"[a-f0-9]{64}", item["sha256"])), "The receipt contains an invalid SHA-256 checksum.")
    require(len({item["name"] for item in files}) == len(files), "The receipt contains duplicate filenames.")
    return identity, files


def validate_remote(draft, identity, files, expected_bucket=None):
    require(isinstance(draft, dict) and draft.get("id") == identity and type(draft.get("id")) is int, "The remote draft identity differs from the receipt.")
    require(draft.get("submitted") is False and draft.get("state") == "unsubmitted", "The remote resource is not an unsubmitted draft.")
    bucket = bucket_url((draft.get("links") or {}).get("bucket"))
    require(expected_bucket is None or bucket == expected_bucket, "The remote draft bucket changed during verification.")
    remote = draft.get("files")
    require(isinstance(remote, list) and len(remote) == len(files) and all(isinstance(item, dict) for item in remote), "The remote draft has missing, extra or invalid files.")
    names = [item.get("filename") for item in remote]
    require(all(isinstance(name, str) for name in names) and len(set(names)) == len(names)
            and set(names) == {item["name"] for item in files}, "The remote draft has missing, extra or duplicate filenames.")
    expected_sizes = {item["name"]: item["size"] for item in files}
    require(all(type(item.get("filesize")) is int and item["filesize"] == expected_sizes[item["filename"]] for item in remote), "Remote file metadata disagrees with the declared byte count.")
    return bucket


def verify(receipt, token, *, session=None):
    identity, files = validate_receipt(receipt)
    client = ReadOnlySandbox(token, session)
    bucket = validate_remote(client.draft(identity), identity, files)
    verified = []
    for expected in files:
        response = client.get(bucket + "/" + quote(expected["name"], safe=""), stream=True)
        size, digest = 0, hashlib.sha256()
        try:
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                require(size <= expected["size"], "Downloaded Sandbox bytes exceed their declared size.")
                digest.update(chunk)
        except requests.RequestException:
            raise RuntimeError("A Sandbox file download was interrupted; verification did not complete.") from None
        finally:
            response.close()
        require(size == expected["size"] and digest.hexdigest() == expected["sha256"], "Downloaded Sandbox bytes failed size or SHA-256 verification.")
        verified.append({"name": expected["name"], "size": size, "sha256": digest.hexdigest(), "matches_pipeline_receipt": True})
    # Recheck the private draft after streaming to reject publication, metadata
    # changes or unexpected files introduced during this verification interval.
    validate_remote(client.draft(identity), identity, files, expected_bucket=bucket)
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "verification": "Independent read-only GET of draft state before and after downloading every remote file; all sizes and SHA-256 match the pipeline receipt",
            "api_origin": SANDBOX, "deposition_id": identity, "draft_url": f"{SANDBOX}/uploads/{identity}",
            "submitted": False, "state": "unsubmitted", "publication_attempted": False,
            "file_count": len(verified), "files": verified, "success": True}


def write_proof(path, proof, token):
    target = Path(path)
    if target.exists():
        previous = read_document(target)
        observation = previous.get("account_ui_observation") if isinstance(previous, dict) and previous.get("deposition_id") == proof["deposition_id"] else None
        if isinstance(observation, str) and token not in observation:
            proof["account_ui_observation"] = observation
    serialized = json.dumps(proof, indent=2)
    require(token not in serialized, "Verification output was rejected by the credential-disclosure check.")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized + "\n"); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, help="Downloaded zenodo-sandbox-receipt.json")
    parser.add_argument("--environment-file", required=True, help="Private existing backend JSON environment; never echoed")
    parser.add_argument("--output", required=True, help="Sanitized independent verification JSON")
    args = parser.parse_args(argv)
    try:
        require(Path(args.output).resolve() not in {Path(args.receipt).resolve(), Path(args.environment_file).resolve()}, "Output must differ from the receipt and credential file.")
        receipt_path = Path(args.receipt)
        require(receipt_path.stat().st_size <= 2 * 1024 * 1024, "The receipt exceeds 2 MiB.")
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        token = load_token(args.environment_file)
        proof = verify(receipt, token)
        proof["receipt_sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
        write_proof(args.output, proof, token)
        print(json.dumps({"success": True, "deposition_id": proof["deposition_id"], "submitted": False, "state": "unsubmitted", "verified_files": proof["file_count"]}))
        return 0
    except Exception as exc:
        # Never expose transport exceptions, raw responses, file contents or keys.
        detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) and not isinstance(exc, requests.RequestException) else "Sandbox read-only verification could not complete."
        secret = locals().get("token")
        if secret:
            detail = detail.replace(secret, "[redacted]")
        print(json.dumps({"success": False, "error": detail}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
