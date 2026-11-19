"""Prepare one model, validate its metadata and verify its Sandbox draft."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from urllib.parse import quote, urlencode

import requests

from external_code.webhdp_link_zenodo.runner import API, SANDBOX, SandboxClient, checksum, draft_id, sandbox_bucket, save_json
from services import model_publication_queue as queue
from services.model_publication_accounts import sandbox_token

_rate_limit_lock = threading.Lock()
_retry_after = 0.0


class DraftClient(SandboxClient):
    def request(self, method, url, *, expected, **kwargs):
        def send(statuses):
            return super(DraftClient, self).request(method, url, expected=statuses, **kwargs)

        body = kwargs.get("data")
        position = body.tell() if hasattr(body, "tell") else None
        return self._with_backoff(send, expected, method, body=body, position=position)

    def preview_link(self, identity, checkpoint):
        if checkpoint.is_file():
            return json.loads(checkpoint.read_text()).get("url")
        if type(identity) is not int or identity <= 0:
            raise ValueError("Invalid Sandbox draft identifier.")
        expires = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        endpoint = f"{SANDBOX}/api/records/{identity}/access/links"
        save_json(checkpoint, {"state": "creating"})

        def send(_):
            return self._session.post(endpoint, headers=self._headers, allow_redirects=False,
                                      timeout=(8, 20), json={"permission": "preview", "expires_at": expires})

        response = self._with_backoff(send, {201, 403, 404}, "POST")
        if response.status_code != 201:
            return None
        payload = response.json()
        token = payload.get("token", "")
        if (payload.get("permission") != "preview" or not isinstance(token, str) or len(token) > 2000
                or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}", token)):
            raise ValueError("Sandbox did not provide a valid preview link.")
        url = f"{SANDBOX}/records/{identity}?" + urlencode({"preview": 1, "token": token})
        save_json(checkpoint, {"url": url})
        return url

    @staticmethod
    def _with_backoff(send, expected, method, *, body=None, position=None):
        global _retry_after
        for _ in range(4):
            with _rate_limit_lock:
                delay = _retry_after - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if position is not None:
                body.seek(position)
            response = send(set(expected) | {429, 503})
            if response.status_code not in {429, 503}:
                return response
            try:
                reset_at = int(response.headers.get("X-RateLimit-Reset", 0)) - time.time()
                delay = min(65, max(3, reset_at + 1, int(response.headers.get("Retry-After", 8))))
            except ValueError:
                delay = 15
            with _rate_limit_lock:
                _retry_after = max(_retry_after, time.monotonic() + delay)
            if method == "POST" and response.status_code != 429:
                break  # A server error can follow creation. Do not repeat an uncertain POST.
        raise RuntimeError("Zenodo Sandbox is busy. Review the run before submitting it again.")


def _open_draft(client, metadata, checkpoint):
    if checkpoint.is_file():
        state = json.loads(checkpoint.read_text())
        identity = state.get("id")
        if not identity:
            raise RuntimeError("Zenodo did not confirm a draft identity. Contact the operator before repeating this run.")
        return client.draft(identity), state["bucket"]
    save_json(checkpoint, {"state": "creating"})
    created = client.request("POST", API, expected={201}, json={"metadata": metadata}).json()
    identity = draft_id(created)
    bucket = sandbox_bucket(created.get("links", {}).get("bucket"))
    save_json(checkpoint, {"id": identity, "bucket": bucket})
    return created, bucket


def _send_assets(client, draft, bucket, destination, assets, report):
    identity = draft_id(draft)
    if sandbox_bucket(draft.get("links", {}).get("bucket")) != bucket:
        raise RuntimeError("Zenodo Sandbox returned a changed draft bucket.")
    existing = {item["filename"]: item for item in draft.get("files", [])}
    expected = {}
    for index, item in enumerate(assets, start=1):
        name = item["name"]
        path = destination / name
        digest = checksum(path, "md5")
        expected[name] = (item["size"], digest)
        report(f"{index} of {len(assets)} files", None)
        if name in existing:
            prior = existing[name]
            if (prior.get("filesize"), prior.get("checksum", "").removeprefix("md5:")) == expected[name]:
                continue
        with path.open("rb") as content:
            result = client.request("PUT", f"{bucket}/{quote(name, safe='')}", expected={200, 201},
                                    data=content).json()
        if (result.get("size"), result.get("checksum", "").removeprefix("md5:")) != expected[name]:
            raise RuntimeError("Zenodo Sandbox could not verify an uploaded file.")
    final = client.draft(identity)
    actual = {item["filename"]: (item.get("filesize"), item.get("checksum", "").removeprefix("md5:"))
              for item in final.get("files", [])}
    if actual != expected:
        raise RuntimeError("Zenodo Sandbox did not confirm the complete file inventory.")
    return {"id": identity, "url": f"{SANDBOX}/uploads/{identity}", "environment": "sandbox",
            "title": final.get("metadata", {}).get("title"), "files": assets}


def export_glb(prepared, destination, model):
    """Package the repaired geometry and textures as one self-contained model."""
    source = prepared / model["model"]
    if model["format"] == "glb":
        shutil.copyfile(source, destination)
        return

    import trimesh

    try:
        scene = trimesh.load_scene(source, process=False)
        if scene.is_empty:
            raise ValueError("No usable model geometry was found.")
        data = scene.export(file_type="glb")
        if data[:4] != b"glTF" or len(data) > 64 * 1024**2:
            raise ValueError("The GLB export is invalid or exceeds 64 MiB.")
        destination.write_bytes(data)
    except (OSError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("The prepared model could not be exported as GLB. Check its geometry and materials.") from exc


def _file(destination, name, fmt):
    return {"name": name, "size": (destination / name).stat().st_size, "format": fmt}


def _record_metadata(mapped, mode, source, msf):
    return {"title": mapped["title"], "creators": [{"name": person["name"]} for person in mapped["creators"]],
            "license": mapped.get("license"), "source": "form" if mode == "form" else "msf",
            "description": mapped.get("description"), "keywords": mapped.get("keywords", []),
            "model_path": source, "spreadsheet": msf.name if msf else None}


def _deposit_record(client, record, mapped, destination, workspace, report, allow_preview):
    from services.model_deposit_metadata import generate_deposit_metadata

    report("creating_draft")
    draft, bucket = _open_draft(client, mapped["zenodo"], workspace / "remote-draft.json")
    report("generating_metadata")
    files = record["files"]
    outputs = generate_deposit_metadata(
        destination, draft=draft, metadata=mapped, main_file_key="model.glb",
        additional_files=[{"key": item["name"], "size": item["size"]} for item in files],
        progress=lambda standard, i, total: report("generating_metadata", f"{i + 1} of {total} formats" if standard else None),
    )
    files.extend(_file(destination, name, fmt) for fmt, name in outputs.items())
    report("uploading")
    record["draft"] = _send_assets(client, draft, bucket, destination, files, lambda detail, _: report("uploading", detail))
    if allow_preview:
        try:
            preview = client.preview_link(record["draft"]["id"], workspace / "sandbox-preview.json")
            if preview:
                record["draft"]["preview_url"] = preview
        except (ValueError, RuntimeError, requests.RequestException):
            record["warnings"].append("Sandbox could not provide a separate preview link.")


def process(app, base, job):
    from routes.model_publication_routes import LIBRARY, sample_catalog
    from services.model_deposit_metadata import read_deposit_metadata
    from services.model_preparation_service import prepare_model, prepare_sample_batch

    job_id = job["id"]
    workspace = base / job_id
    prepared = workspace / "prepared"
    destination = workspace / "results"
    parameters = json.loads(job["input_json"])
    practice = parameters.get("run_mode") == "practice"
    mode = parameters["metadata_source"]
    sample_id = parameters["practice_sample_id"] if practice else parameters["sample_id"]
    is_batch = parameters.get("model_count", 1) > 1
    result = {"sample_id": sample_id}
    if is_batch:
        result["records"] = []

    def report(stage, detail=None):
        queue.update(base, job_id, stage, detail=detail, result=result)

    try:
        with app.app_context():
            if not practice:
                token = sandbox_token(job["user_id"], bool(job["demo_window"]))
                if not token:
                    raise ValueError("The active Zenodo Sandbox credential is missing.")
            library = {entry["id"]: entry for entry in sample_catalog()}
            entry = library[sample_id] if sample_id else None
            archive = LIBRARY / entry["filename"] if entry else workspace / ("model" + parameters["extension"])
            shutil.rmtree(prepared, ignore_errors=True)
            models = (prepare_sample_batch(archive, prepared, [row["filename"] for row in entry["records"]])
                      if is_batch else [prepare_model(archive, prepared)])
            mapped_records = []
            for index, model in enumerate(models, 1):
                relative = str(index) if is_batch else ""
                model_dir = prepared / relative
                record_dir = destination / relative
                record_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                export_glb(model_dir, record_dir / "model.glb", model)
                files = [_file(record_dir, "model.glb", "Model")]
                record_sample_id = entry["records"][index - 1]["sample_id"] if is_batch else sample_id
                if record_sample_id:
                    shutil.copyfile(LIBRARY / library[record_sample_id]["preview"], record_dir / "preview.png")
                    files.append(_file(record_dir, "preview.png", "Preview"))

                msf = None
                if mode == "upload":
                    msf = workspace / ("metadata" + parameters["msf_extension"])
                elif mode == "archive":
                    if not is_batch and not model.get("msf"):
                        raise ValueError("No Metadata Source File (MSF) was found in this model package.")
                    msf = prepared / ("metadata.csv" if is_batch else model["msf"])
                source = parameters.get("original_filename") if parameters["extension"] == ".glb" else model["model"]
                source = source or model["model"]
                record = {"sample_id": record_sample_id, "model": model["model"], "input_format": model["format"],
                          "source_files": model["files"], "files": files, "repairs": model["repairs"],
                          "warnings": model["warnings"]}
                if is_batch:
                    result["records"].append(record)
                    for item in files:
                        item["path"] = f"{relative}/{item['name']}"
                else:
                    result.update(record)
                    record = result
                report("mapping_metadata")
                mapped = read_deposit_metadata(source, msf_path=msf, form_metadata=parameters["metadata"])
                mapped_fields = mapped["formats"]["jsonld"] if practice else mapped["zenodo"]
                record["metadata"] = _record_metadata(mapped_fields, mode, source, msf)
                if practice:
                    report("preparing_downloads")
                    shutil.copyfile(msf, record_dir / "metadata.csv")
                    save_json(record_dir / "metadata.json", record["metadata"])
                    files.extend([_file(record_dir, "metadata.csv", "Source spreadsheet"),
                                  _file(record_dir, "metadata.json", "Mapped metadata")])
                mapped_records.append((mapped, record, record_dir, relative))

            if practice:
                report("completed")
                return

            client = DraftClient(token)
            try:
                for index, (mapped, record, record_dir, relative) in enumerate(mapped_records, 1):
                    def record_report(stage, detail=None):
                        if is_batch:
                            for item in record["files"]:
                                item["path"] = f"{relative}/{item['name']}"
                            label = f"Model {index} of {len(mapped_records)}"
                            detail = f"{label} · {detail}" if detail else label
                        report(stage, detail)
                    worker_dir = workspace / "records" / relative if is_batch else workspace
                    worker_dir.mkdir(parents=True, exist_ok=True)
                    _deposit_record(client, record, mapped, record_dir, worker_dir, record_report,
                                    bool(job["demo_window"] and sample_id))
                    record_report("uploading")
            finally:
                client._session.close()
            report("completed")
            if archive.parent == workspace:
                archive.unlink(missing_ok=True)
            if mode == "upload":
                msf.unlink(missing_ok=True)
    except (ValueError, RuntimeError) as exc:
        app.logger.warning("Model publication run %s failed in processing (%s).", job_id, type(exc).__name__)
        queue.update(base, job_id, "failed", error=str(exc)[:500])
    except Exception as exc:
        app.logger.error("Model publication run %s was interrupted (%s).", job_id, type(exc).__name__)
        queue.update(base, job_id, "failed", error="Processing could not finish. Contact the operator with the run ID.")
    finally:
        shutil.rmtree(prepared, ignore_errors=True)
        queue.trim(base, job_id)


def run_worker(app, base, *, stop):
    os.umask(0o077)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (base / ".worker-lock").open("ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        queue.recover(base)
        beat = base / ".heartbeat"
        practice_beat = base / queue.PRACTICE_HEARTBEAT
        try:
            with ThreadPoolExecutor(max_workers=queue.WORKER_CAPACITY) as executor:
                running = set()
                cleanup_at = 0
                while not stop.is_set():
                    beat.touch()
                    practice_beat.touch()
                    if time.monotonic() >= cleanup_at:
                        queue.expire(base)
                        cleanup_at = time.monotonic() + 60
                    for future in tuple(running):
                        if future.done():
                            future.result()
                            running.remove(future)
                    while len(running) < queue.WORKER_CAPACITY and (job := queue.claim(base)):
                        running.add(executor.submit(process, app, base, job))
                    stop.wait(0.5)
        finally:
            practice_beat.unlink(missing_ok=True)
            beat.unlink(missing_ok=True)
