"""Public sample library and authenticated access to guided model publication."""

import csv
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4
from zipfile import ZipFile

from flask import Blueprint, request, send_file
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from werkzeug.exceptions import RequestEntityTooLarge

from api_utils import APIResponse
from database.database import db
from database.models import User
from services import model_publication_queue as queue
from services.model_publication_accounts import demo_expiry, is_demo, sandbox_token

model_publication_bp = Blueprint("model_publication", __name__)
@model_publication_bp.after_request
def keep_job_responses_private(response):
    if request.endpoint not in {"model_publication.samples", "model_publication.sample_download", "model_publication.sample_preview"}:
        response.headers["Cache-Control"] = "private, no-store"
    return response


LIBRARY = Path(__file__).resolve().parents[1] / "datasets" / "quick-publication"


@lru_cache(maxsize=1)
def sample_catalog():
    entries = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))["datasets"]
    for entry in entries:
        archive = LIBRARY / entry["filename"]
        entry["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        if "records" not in entry:
            with ZipFile(archive) as bundle:
                entry["records"] = list(csv.DictReader(bundle.read("metadata.csv").decode().splitlines()))
    return entries


@lru_cache(maxsize=1)
def sample_hashes():
    return {entry["sha256"]: entry["id"] for entry in sample_catalog()}


@model_publication_bp.route("/samples")
def samples():
    published = os.environ.get("WEBHDP_MODEL_PUBLICATION_PUBLISHED_EXAMPLE", "")
    if not re.fullmatch(r"https://sandbox\.zenodo\.org/records/[1-9][0-9]*", published):
        published = None
    return APIResponse.success({"datasets": sample_catalog(), "published_example": published})


def _sample_file(sample_id, *, preview=False):
    entry = next((item for item in sample_catalog() if item["id"] == sample_id), None)
    if entry is None:
        return APIResponse.not_found("Sample model")
    filename = entry.get("preview") if preview else entry["filename"]
    if not filename:
        return APIResponse.not_found("Sample preview")
    return send_file(LIBRARY / filename, as_attachment=not preview, max_age=3600)


@model_publication_bp.route("/samples/<sample_id>")
def sample_download(sample_id):
    return _sample_file(sample_id)


@model_publication_bp.route("/samples/<sample_id>/preview")
def sample_preview(sample_id):
    return _sample_file(sample_id, preview=True)


@model_publication_bp.route("/availability")
@jwt_required()
def availability():
    user = db.session.get(User, int(get_jwt_identity()))
    demo = is_demo(user)
    return APIResponse.success({"ready": queue.enabled() and queue.worker_ready(queue.root()),
                                "credential_ready": bool(sandbox_token(user.id, demo)), "demo": demo})


@model_publication_bp.route("/queue")
@jwt_required()
def queue_status():
    return APIResponse.success(queue.snapshot(queue.root()))


def _owned_jobs(job_id=None):
    user = db.session.get(User, int(get_jwt_identity()))
    return queue.get_jobs(queue.root(), user_id=user.id, job_id=job_id,
                          sign_in=queue.sign_in_key(get_jwt()["jti"]) if is_demo(user) else None)


@model_publication_bp.route("/jobs")
@jwt_required()
def jobs():
    return APIResponse.success({"jobs": [queue.serialize(job) for job in _owned_jobs()]})


@model_publication_bp.route("/jobs/<job_id>")
@jwt_required()
def job_status(job_id):
    owned = _owned_jobs(job_id)
    if not owned:
        return APIResponse.not_found("Processing run")
    return APIResponse.success({"job": queue.serialize(owned[0])})


@model_publication_bp.route("/jobs/<job_id>/files/<path:filename>")
@jwt_required()
def job_file(job_id, filename):
    owned = _owned_jobs(job_id)
    if not owned:
        return APIResponse.not_found("Result file")
    job = queue.serialize(owned[0])
    results = job.get("records") or [job]
    allowed = {item.get("path", item["name"]) for record in results for item in record.get("files", [])}
    if filename not in allowed:
        return APIResponse.not_found("Result file")
    folder = (queue.root() / job_id / "results").resolve()
    path = (folder / filename).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        return APIResponse.not_found("Result file")
    response = send_file(path, as_attachment=True, mimetype="application/octet-stream")
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _read_input(user):
    request.max_content_length = queue.MAX_ARCHIVE_BYTES + queue.MAX_MSF_BYTES + 128 * 1024
    if request.content_length and request.content_length > request.max_content_length:
        raise RequestEntityTooLarge()
    request_key = request.headers.get("Idempotency-Key") or uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", request_key):
        raise queue.QueueError("Invalid upload request identity.")
    archive = request.files.get("archive")
    msf = request.files.get("msf")
    sample_id = request.form.get("sample_id")
    if bool(archive) == bool(sample_id):
        raise queue.QueueError("Choose one sample or upload one model.")
    if sample_id and sample_id not in {entry["id"] for entry in sample_catalog()}:
        raise queue.QueueError("The selected sample is unavailable.")
    suffix = Path(archive.filename).suffix.lower() if archive else None
    if archive:
        if suffix not in {".zip", ".glb"}:
            raise queue.QueueError("Upload a ZIP package or a self-contained GLB.")
        size = archive.stream.seek(0, os.SEEK_END)
        archive.stream.seek(0)
        if not 0 < size <= queue.MAX_ARCHIVE_BYTES:
            raise queue.QueueError("The model upload must be between 1 byte and 24 MiB.", 413)
        if size <= 4 * 1024**2 and suffix == ".zip":
            sample_id = sample_hashes().get(hashlib.file_digest(archive.stream, "sha256").hexdigest())
            archive.stream.seek(0)
        if is_demo(user) and not sample_id:
            raise queue.QueueError("This demonstration accepts the models from the sample library. Choose one above or upload an unchanged sample ZIP.")

    metadata = {field: request.form.get(field, "").strip() for field in ("title", "creator", "description")}
    mode = request.form.get("metadata_source") or ("upload" if msf else "form" if any(metadata.values()) else "archive")
    if mode not in {"archive", "upload", "form"} or (mode == "upload") != bool(msf):
        raise queue.QueueError("Select one metadata source.")
    if is_demo(user) and (mode != "archive" or any(metadata.values())):
        raise queue.QueueError("The demonstration uses the sample package's metadata.")
    sample = next((entry for entry in sample_catalog() if entry["id"] == sample_id), None)
    if sample and sample["format"] == "batch" and mode != "archive":
        raise queue.QueueError("The batch sample needs its original metadata spreadsheet.")
    msf_suffix = Path(msf.filename).suffix.lower() if msf else ""
    if msf:
        size = msf.stream.seek(0, os.SEEK_END)
        msf.stream.seek(0)
        if msf_suffix not in {".csv", ".xls", ".xlsx"} or not 0 < size <= queue.MAX_MSF_BYTES:
            raise queue.QueueError("Choose a CSV, XLS or XLSX metadata file up to 1 MiB.")
    if mode == "form" and (not all(metadata.values()) or any(len(metadata[field]) > limit for field, limit in
                                                               (("title", 250), ("creator", 200), ("description", 5000)))):
        raise queue.QueueError("Enter a title, creator and description within the indicated lengths.")
    if suffix == ".glb" and mode == "archive":
        raise queue.QueueError("For a standalone GLB, enter metadata or select an MSF.")
    return request_key, archive, msf, {"sample_id": sample_id, "extension": suffix, "msf_extension": msf_suffix,
                                        "title": metadata.get("title") or (sample["title"] if sample else None),
                                        "model_count": len(sample["records"]) if sample else 1,
                                        "original_filename": Path(archive.filename).name if archive else None,
                                        "metadata_source": mode, "metadata": metadata if mode == "form" else {}}


@model_publication_bp.route("/jobs", methods=["POST"])
@jwt_required()
def submit_job():
    base = queue.root()
    user = db.session.get(User, int(get_jwt_identity()))
    demo = is_demo(user)
    if not queue.enabled() or not queue.worker_ready(base):
        return APIResponse.error("WORKER_OFFLINE", "Model processing is temporarily unavailable.", 503)
    if not sandbox_token(user.id, demo):
        return APIResponse.error("SANDBOX_REQUIRED", "Set an active Zenodo Sandbox credential before starting a run.", 409)
    try:
        request_key, archive, msf, parameters = _read_input(user)
        demo_window = demo_expiry(user.id) if demo else 0
        job_id, created = queue.reserve(base, user_id=user.id, sign_in=queue.sign_in_key(get_jwt()["jti"]),
                                        request_key=request_key, demo_window=demo_window, parameters=parameters)
        if created:
            workspace = base / job_id
            try:
                workspace.mkdir(mode=0o700)
                if archive and not parameters["sample_id"]:
                    with (workspace / ("model" + parameters["extension"])).open("wb") as stream:
                        shutil.copyfileobj(archive.stream, stream)
                if msf:
                    with (workspace / ("metadata" + parameters["msf_extension"])).open("wb") as stream:
                        shutil.copyfileobj(msf.stream, stream)
                queue.enqueue(base, job_id)
            except Exception:
                queue.abandon_upload(base, job_id)
                raise
        job = _owned_jobs(job_id)[0]
        return APIResponse.success({"job": queue.serialize(job)}, status_code=202 if created else 200)
    except queue.QueueError as exc:
        return APIResponse.error("MODEL_PUBLICATION_INPUT", str(exc), exc.status)
    except RequestEntityTooLarge:
        return APIResponse.error("MODEL_PUBLICATION_INPUT", "Model uploads are limited to 24 MiB plus an optional 1 MiB MSF.", 413)
