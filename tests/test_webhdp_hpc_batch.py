import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hpc_singularity" / "remote" / "webhdp_hpc_batch.py"
SPEC = importlib.util.spec_from_file_location("webhdp_hpc_batch", SCRIPT)
webhdp_hpc_batch = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["webhdp_hpc_batch"] = webhdp_hpc_batch
SPEC.loader.exec_module(webhdp_hpc_batch)


def write_config(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_prepare_chunks_matches_ply_files_and_writes_stateful_report(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "a.ply").write_text("ply\n", encoding="utf-8")
    (dataset / "b.ply").write_text("ply\n", encoding="utf-8")
    (dataset / "ignore.glb").write_text("glb\n", encoding="utf-8")
    msf = tmp_path / "metadata.csv"
    msf.write_text("Filename,Title\na.ply,A\nb.ply,B\nmissing.ply,Missing\n", encoding="utf-8")
    root = tmp_path / "root"
    (root / "data/local_input").mkdir(parents=True)
    config_path = write_config(
        tmp_path,
        {
            "root": str(root),
            "dataset_dir": str(dataset),
            "msf_path": str(msf),
            "output_dir": str(root / "data/local_input/batch"),
            "state_dir": str(root / "run/state"),
            "file_extensions": [".ply"],
            "filename_column": "Filename",
            "chunk_size": 1,
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)

    report = webhdp_hpc_batch.prepare_chunks(config)

    assert report["matched_records"] == 2
    assert report["missing_records"] == 1
    assert report["chunk_count"] == 2
    assert Path(report["chunks"][0]["chunk_dir"], "chunk.json").is_file()
    assert Path(report["chunks"][0]["files_dir"], "a.ply").is_symlink()


def test_artifact_audit_requires_configured_outputs():
    records_payload = {
        "data": {
            "records": [
                {
                    "record_id": 1,
                    "source_file_path": "/x/a.ply",
                    "files": [{"filename": "a.usdz"}, {"filename": "edm.xml"}],
                }
            ]
        }
    }

    audit = webhdp_hpc_batch.artifact_audit(records_payload, webhdp_hpc_batch.DEFAULT_REQUIRED_ARTIFACTS)

    assert audit["ok"] is False
    assert audit["summary"]["incomplete"] == 1
    assert "png_renders" in audit["records"][0]["missing"]


def test_prepare_chunks_rejects_duplicate_dataset_filenames(tmp_path):
    dataset = tmp_path / "dataset"
    (dataset / "a").mkdir(parents=True)
    (dataset / "b").mkdir()
    (dataset / "a" / "same.ply").write_text("ply\n", encoding="utf-8")
    (dataset / "b" / "same.ply").write_text("ply\n", encoding="utf-8")
    msf = tmp_path / "metadata.csv"
    msf.write_text("Filename,Title\nsame.ply,Same\n", encoding="utf-8")
    root = tmp_path / "root"
    config_path = write_config(
        tmp_path,
        {
            "root": str(root),
            "dataset_dir": str(dataset),
            "msf_path": str(msf),
            "output_dir": str(root / "data/local_input/batch"),
            "state_dir": str(root / "run/state"),
            "file_extensions": [".ply"],
        },
    )

    with pytest.raises(RuntimeError, match="unique"):
        webhdp_hpc_batch.prepare_chunks(webhdp_hpc_batch.load_config(config_path))


def test_artifact_audit_verifies_existing_nonempty_outputs(tmp_path):
    names = [
        "a.ply",
        "a.usdz",
        "view_1.png",
        "view_2.png",
        "view_3.png",
        "view_4.png",
        "view_5.png",
        "edm.xml",
        "mets.xml",
        "iiif.json",
    ]
    files = []
    for name in names:
        path = tmp_path / name
        path.write_text("x", encoding="utf-8")
        files.append({"filename": name, "absolute_path": str(path)})
    validation_path = tmp_path / "edm.validation.json"
    validation_path.write_text(json.dumps({"valid": True}), encoding="utf-8")
    files.append({"filename": "edm.validation.json", "absolute_path": str(validation_path)})
    records_payload = {"data": {"records": [{"record_id": 1, "files": files}]}}

    audit = webhdp_hpc_batch.artifact_audit(records_payload, webhdp_hpc_batch.DEFAULT_REQUIRED_ARTIFACTS)

    assert audit["ok"] is True
    assert audit["summary"]["complete"] == 1


def test_artifact_audit_rejects_invalid_edm_validation_report(tmp_path):
    required = dict(webhdp_hpc_batch.DEFAULT_REQUIRED_ARTIFACTS)
    required["source_model"] = False
    required["usdz"] = False
    required["png_renders"] = 0
    required["edm_xml"] = False
    required["mets_mods_xml"] = False
    required["iiif_json"] = False
    validation_path = tmp_path / "edm.validation.json"
    validation_path.write_text(json.dumps({"valid": False, "errors": ["bad"]}), encoding="utf-8")
    records_payload = {
        "data": {
            "records": [
                {
                    "record_id": 1,
                    "files": [{"filename": "edm.validation.json", "absolute_path": str(validation_path)}],
                }
            ]
        }
    }

    audit = webhdp_hpc_batch.artifact_audit(records_payload, required)

    assert audit["ok"] is False
    assert audit["records"][0]["reason_code"] == "missing_required_artifacts"
    assert "edm_validation" in audit["records"][0]["missing"]


def test_submit_chunk_stops_on_nonretryable_recovery_state(tmp_path, monkeypatch):
    root = tmp_path / "root"
    state_dir = root / "run/state"
    config_path = write_config(
        tmp_path,
        {
            "root": str(root),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
            "state_dir": str(state_dir),
            "output_dir": str(root / "data/local_input/batch"),
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)
    webhdp_hpc_batch.write_state(
        webhdp_hpc_batch.state_file_for(config, "chunk_0001"),
        {"chunk_id": "chunk_0001", "status": "quarantined", "retryable": False, "reason_code": "artifact_audit_failed"},
    )
    monkeypatch.setattr(webhdp_hpc_batch, "active_chunk_job_id", lambda _chunk_id: None)

    with pytest.raises(RuntimeError, match="manual recovery"):
        webhdp_hpc_batch.submit_chunk(config, {"chunk_id": "chunk_0001"})


def test_stale_allocation_state_resets_old_executing_run(tmp_path, monkeypatch):
    root = tmp_path / "root"
    config_path = write_config(
        tmp_path,
        {
            "root": str(root),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
            "state_dir": str(root / "run/state"),
            "output_dir": str(root / "data/local_input/batch"),
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)
    webhdp_hpc_batch.write_state(
        webhdp_hpc_batch.state_file_for(config, "chunk_0001"),
        {"chunk_id": "chunk_0001", "status": "executing", "allocation_id": "old", "session_id": 7, "run_id": "run-old"},
    )
    monkeypatch.setenv("SLURM_JOB_ID", "new")

    state = webhdp_hpc_batch.reset_stale_allocation_state(
        config,
        "chunk_0001",
        webhdp_hpc_batch.load_state(webhdp_hpc_batch.state_file_for(config, "chunk_0001")),
    )

    assert state["status"] == "not_started"
    assert state["previous_session_id"] == 7
    assert state["previous_run_id"] == "run-old"


def test_publish_mode_maps_to_record_atomic_operations(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "root": str(tmp_path),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
            "publish_mode": "publish",
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)

    assert webhdp_hpc_batch.publish_operations_for_mode(config) == [
        "create_drafts",
        "upload_files",
        "publish_records",
    ]


def test_hpc_partition_defaults_and_round_robin_strategy(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "root": str(tmp_path),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)

    assert config.partitions == ["vascunet", "vis", "gpu", "gpu-test"]
    assert config.max_parallel_jobs == 2
    assert webhdp_hpc_batch.partition_for_attempt(config, 1, 0) == "vascunet"
    assert webhdp_hpc_batch.partition_for_attempt(config, 1, 1) == "vis"
    assert webhdp_hpc_batch.partition_for_attempt(config, 2, 1) == "gpu"


def test_normalize_slurm_state_handles_compound_states():
    assert webhdp_hpc_batch.normalize_slurm_state("FAILED+") == "FAILED"
    assert webhdp_hpc_batch.normalize_slurm_state("CANCELLED by 123") == "CANCELLED"
    assert webhdp_hpc_batch.choose_slurm_state(["COMPLETED", "OUT_OF_MEMORY"]) == "OUT_OF_MEMORY"


def test_run_publish_operations_uses_session_batch_routes(tmp_path, monkeypatch):
    config_path = write_config(
        tmp_path,
        {
            "root": str(tmp_path),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
            "publish_operations": ["publish_records"],
            "api": {"base_url": "http://webhdp/api/v1"},
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)
    calls = []

    def fake_request(method, url, token=None, payload=None, timeout=120):
        calls.append({"method": method, "url": url, "payload": payload, "token": token})
        if method == "GET" and url.endswith("/operations/summary?is_sandbox=false"):
            return {"data": {"actionable_operations": {"publish_records": {"target_ids": [1, 2]}}}}
        if method == "POST":
            return {"data": {"task_id": "task-1"}}
        return {"data": {"state": "SUCCESS", "status": "completed", "result": {"summary": {"failed": 0}}}}

    monkeypatch.setattr(webhdp_hpc_batch, "request_json", fake_request)

    results = webhdp_hpc_batch.run_publish_operations(config, "token", 11, [1, 2])

    assert results[0]["operation"] == "publish_records"
    assert calls[0]["url"] == "http://webhdp/api/v1/sessions/11/operations/summary?is_sandbox=false"
    assert calls[1]["url"] == "http://webhdp/api/v1/sessions/11/batch-operations"
    assert calls[1]["payload"]["target_ids"] == [1, 2]
    assert calls[2]["url"] == "http://webhdp/api/v1/sessions/11/batch-operations/task-1"


def test_run_publish_operations_skips_already_ineligible_records(tmp_path, monkeypatch):
    config_path = write_config(
        tmp_path,
        {
            "root": str(tmp_path),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
            "publish_operations": ["create_drafts"],
            "api": {"base_url": "http://webhdp/api/v1"},
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)
    calls = []

    def fake_request(method, url, token=None, payload=None, timeout=120):
        calls.append({"method": method, "url": url, "payload": payload})
        return {"data": {"actionable_operations": {"create_drafts": {"target_ids": []}}}}

    monkeypatch.setattr(webhdp_hpc_batch, "request_json", fake_request)

    results = webhdp_hpc_batch.run_publish_operations(config, "token", 11, [1, 2])

    assert results == [{"operation": "create_drafts", "status": "skipped", "reason": "no_eligible_records"}]
    assert len(calls) == 1


def test_parallel_scheduler_keeps_configured_jobs_active(tmp_path, monkeypatch):
    config_path = write_config(
        tmp_path,
        {
            "root": str(tmp_path),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
            "state_dir": str(tmp_path / "state"),
            "max_parallel_jobs": 3,
            "poll_seconds": 0,
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)
    chunks = [{"chunk_id": f"chunk_{index:04d}", "ordinal": index} for index in range(1, 5)]
    job_to_chunk = {}
    submitted_batches = []

    def fake_submit(config, chunk, partition, attempt):
        job_id = f"job-{chunk['chunk_id']}"
        job_to_chunk[job_id] = chunk["chunk_id"]
        submitted_batches.append((chunk["chunk_id"], partition, len(job_to_chunk)))
        webhdp_hpc_batch.update_chunk_state(config, chunk["chunk_id"], status="queued", slurm_job_id=job_id, slurm_attempt=attempt)
        return job_id

    def fake_job_state(job_id):
        chunk_id = job_to_chunk[job_id]
        webhdp_hpc_batch.update_chunk_state(config, chunk_id, status="completed")
        return "COMPLETED"

    monkeypatch.setattr(webhdp_hpc_batch, "submit_chunk_job", fake_submit)
    monkeypatch.setattr(webhdp_hpc_batch, "job_state", fake_job_state)
    monkeypatch.setattr(webhdp_hpc_batch, "active_chunk_job_id", lambda _chunk_id: None)

    webhdp_hpc_batch.submit_chunks_parallel(config, chunks)

    assert submitted_batches[:3] == [
        ("chunk_0001", "vascunet", 1),
        ("chunk_0002", "vis", 2),
        ("chunk_0003", "gpu", 3),
    ]
    assert submitted_batches[3][0] == "chunk_0004"


def test_wait_for_job_cancels_after_queue_timeout(tmp_path, monkeypatch):
    config_path = write_config(
        tmp_path,
        {
            "root": str(tmp_path),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
            "state_dir": str(tmp_path / "state"),
            "partition_queue_timeout_seconds": 10,
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)
    clock = {"value": 0}
    commands = []

    monkeypatch.setattr(webhdp_hpc_batch, "job_state", lambda _job_id: "PENDING")
    monkeypatch.setattr(webhdp_hpc_batch.time, "time", lambda: clock["value"])
    monkeypatch.setattr(webhdp_hpc_batch.time, "sleep", lambda seconds: clock.__setitem__("value", clock["value"] + seconds))
    monkeypatch.setattr(webhdp_hpc_batch, "run", lambda command, check=True, env=None: commands.append(command) or type("Result", (), {"stdout": "", "stderr": "", "returncode": 0})())

    state = webhdp_hpc_batch.wait_for_job(config, "123", poll_seconds=5)

    assert state == "QUEUE_TIMEOUT"
    assert ["scancel", "123"] in commands


def test_report_writes_json_and_csv(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "root": str(tmp_path),
            "dataset_dir": str(tmp_path),
            "msf_path": str(tmp_path / "msf.csv"),
            "state_dir": str(tmp_path / "state"),
        },
    )
    config = webhdp_hpc_batch.load_config(config_path)
    (config.report_path.parent).mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(json.dumps({"chunks": [{"chunk_id": "chunk_0001"}], "chunk_count": 1}), encoding="utf-8")
    webhdp_hpc_batch.write_state(webhdp_hpc_batch.state_file_for(config, "chunk_0001"), {"status": "completed"})

    report = webhdp_hpc_batch.write_run_report(config)

    assert Path(report["json"]).is_file()
    assert Path(report["csv"]).is_file()
