"""Durable, host-local queue for the CPU model publication worker."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from uuid import uuid4

from flask import current_app

MAX_ARCHIVE_BYTES = 24 * 1024**2
MAX_MSF_BYTES = 1024**2
MAX_ACTIVE = 40
DEMO_QUEUE_RESERVE = 20
WORKER_CAPACITY = 4
WORKSPACE_FLOOR = 768 * 1024**2
WORKSPACE_BUDGET = 768 * 1024**2
RUN_RESERVATION = 128 * 1024**2
SAMPLE_RESERVATION = 4 * 1024**2
RETENTION_SECONDS = 48 * 3600
ACCOUNT_ACTIVE = 3
ACCOUNT_DAILY_JOBS = 10
ACCOUNT_WORKSPACE_BYTES = 256 * 1024**2
ONE_DAY = 24 * 3600
PRACTICE_HEARTBEAT = ".practice-heartbeat"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL,
    sign_in TEXT NOT NULL, request_key TEXT NOT NULL, demo_window INTEGER NOT NULL,
    created REAL NOT NULL, updated REAL NOT NULL, finished REAL, reserved INTEGER NOT NULL,
    status TEXT NOT NULL, stage TEXT NOT NULL, detail TEXT, error TEXT,
    input_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(user_id, sign_in, request_key)
);
CREATE INDEX IF NOT EXISTS model_job_status ON jobs(status, seq);
CREATE INDEX IF NOT EXISTS model_job_owner ON jobs(user_id, sign_in, seq);
"""


class QueueError(ValueError):
    def __init__(self, message, status=400, *, code="MODEL_PUBLICATION_INPUT", details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or {}


def root():
    return Path(current_app.config.get("MODEL_PUBLICATION_ROOT") or Path(current_app.instance_path) / "model-publication")


def enabled():
    return str(current_app.config.get("MODEL_PUBLICATION_ENABLED", os.environ.get("WEBHDP_MODEL_PUBLICATION_ENABLED", ""))).lower() in {"true", "1"}


def _heartbeat_recent(path):
    try:
        return time.time() - path.stat().st_mtime < 15
    except FileNotFoundError:
        return False


def worker_ready(base):
    return _heartbeat_recent(base / ".heartbeat")


def practice_worker_ready(base):
    return _heartbeat_recent(base / PRACTICE_HEARTBEAT)


@contextmanager
def connection(base, *, write=False):
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    conn = sqlite3.connect(base / "queue.sqlite3", timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            conn.executescript(SCHEMA + "PRAGMA user_version=1;")
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()
    finally:
        conn.close()


def sign_in_key(jti):
    return hashlib.sha256(jti.encode("ascii")).hexdigest()


def snapshot(base):
    """Report only overall load. Each run's position is available to its owner."""
    ready = enabled() and worker_ready(base)
    waiting = running = 0
    if (base / "queue.sqlite3").is_file():
        with connection(base) as conn:
            counts = dict(conn.execute(
                "SELECT status, count(*) FROM jobs WHERE status IN ('queued', 'running') GROUP BY status"
            ).fetchall())
        waiting = counts.get("queued", 0)
        running = counts.get("running", 0)
    return {"queued": waiting, "running": running, "capacity": WORKER_CAPACITY,
            "ready": ready, "updated": int(time.time())}


def _account_usage(conn, user_id, now):
    active, accepted, stored, oldest = conn.execute(
        """SELECT count(CASE WHEN status IN ('staging','queued','running') THEN 1 END),
                  count(CASE WHEN created>=? THEN 1 END), coalesce(sum(reserved), 0),
                  min(CASE WHEN created>=? THEN created END)
           FROM jobs WHERE user_id=? AND demo_window=0""",
        (now - ONE_DAY, now - ONE_DAY, user_id),
    ).fetchone()
    return {"active": active, "active_limit": ACCOUNT_ACTIVE, "accepted_last_24_hours": accepted,
            "daily_limit": ACCOUNT_DAILY_JOBS, "stored_bytes": stored, "storage_limit_bytes": ACCOUNT_WORKSPACE_BYTES,
            "daily_reset_at": int(oldest + ONE_DAY) + 1 if oldest is not None and accepted >= ACCOUNT_DAILY_JOBS else None,
            "retention_seconds": RETENTION_SECONDS}


def account_usage(base, user_id):
    if not (base / "queue.sqlite3").is_file():
        return {"active": 0, "active_limit": ACCOUNT_ACTIVE, "accepted_last_24_hours": 0,
                "daily_limit": ACCOUNT_DAILY_JOBS, "stored_bytes": 0, "storage_limit_bytes": ACCOUNT_WORKSPACE_BYTES,
                "daily_reset_at": None, "retention_seconds": RETENTION_SECONDS}
    with connection(base) as conn:
        return _account_usage(conn, user_id, time.time())


def reserve(base, *, user_id, sign_in, request_key, demo_window, parameters):
    now = time.time()
    with connection(base, write=True) as conn:
        existing = conn.execute(
            "SELECT id, status, input_json FROM jobs WHERE user_id=? AND sign_in=? AND request_key=?",
            (user_id, sign_in, request_key),
        ).fetchone()
        if existing:
            if json.loads(existing["input_json"]).get("run_mode", "sandbox") != parameters.get("run_mode", "sandbox"):
                raise QueueError("This request identity belongs to a different run mode. Start a new request.", 409)
            if existing["status"] == "staging":
                raise QueueError("This upload is still being saved. Try again in a moment.", 409)
            return existing["id"], False
        active, regular_active, pending_storage = conn.execute(
            """SELECT count(*), count(CASE WHEN demo_window=0 THEN 1 END), coalesce(sum(reserved), 0)
               FROM jobs WHERE status IN ('staging','queued','running')"""
        ).fetchone()
        if active >= MAX_ACTIVE or (not demo_window and regular_active >= MAX_ACTIVE - DEMO_QUEUE_RESERVE):
            raise QueueError("The queue is full. Try again after a run finishes.", 429, code="MODEL_PUBLICATION_QUEUE_FULL")
        model_count = parameters.get("model_count", 1)
        sample = parameters.get("sample_id") or parameters.get("practice_sample_id")
        budget = SAMPLE_RESERVATION * model_count if sample else RUN_RESERVATION
        if demo_window:
            total, own = conn.execute(
                """SELECT coalesce(sum(coalesce(json_extract(input_json, '$.model_count'), 1)), 0),
                          count(CASE WHEN sign_in=? AND status IN ('staging','queued','running') THEN 1 END)
                   FROM jobs WHERE user_id=? AND demo_window=?""",
                (sign_in, user_id, demo_window),
            ).fetchone()
            if total + model_count > 30 or own:
                raise QueueError("This demonstration has reached its run limit, or a run on this browser is already in progress.", 429, code="MODEL_PUBLICATION_DEMO_LIMIT")
        else:
            usage = _account_usage(conn, user_id, now)
            if usage["active"] >= ACCOUNT_ACTIVE:
                raise QueueError("Wait for one of your current model runs before submitting another.", 429, code="MODEL_PUBLICATION_ACTIVE_QUOTA", details={"usage": usage})
            if usage["accepted_last_24_hours"] >= ACCOUNT_DAILY_JOBS:
                raise QueueError("You have reached the 24-hour model run limit. Check your account usage for the next available time.", 429, code="MODEL_PUBLICATION_DAILY_QUOTA", details={"usage": usage})
            if usage["stored_bytes"] + budget > ACCOUNT_WORKSPACE_BYTES:
                raise QueueError("Your model workspace is full. Try again after a run finishes or its downloads expire.", 413, code="MODEL_PUBLICATION_STORAGE_QUOTA", details={"usage": usage})
        allocated, regular_storage = conn.execute(
            "SELECT coalesce(sum(reserved), 0), coalesce(sum(CASE WHEN demo_window=0 THEN reserved END), 0) FROM jobs"
        ).fetchone()
        regular_limit = WORKSPACE_BUDGET - DEMO_QUEUE_RESERVE * SAMPLE_RESERVATION
        if (allocated + budget > WORKSPACE_BUDGET
                or (not demo_window and regular_storage + budget > regular_limit)
                or shutil.disk_usage(base).free < WORKSPACE_FLOOR + pending_storage + budget):
            raise QueueError("Processing storage is temporarily full. Try again later.", 507, code="MODEL_PUBLICATION_STORAGE_FULL")
        job_id = uuid4().hex
        conn.execute(
            """INSERT INTO jobs (id,user_id,sign_in,request_key,demo_window,created,updated,reserved,status,stage,input_json)
               VALUES (?,?,?,?,?,?,?,?, 'staging','queued',?)""",
            (job_id, user_id, sign_in, request_key, demo_window, now, now, budget, json.dumps(parameters)),
        )
        return job_id, True


def enqueue(base, job_id):
    with connection(base, write=True) as conn:
        conn.execute("UPDATE jobs SET status='queued', updated=? WHERE id=? AND status='staging'", (time.time(), job_id))


def abandon_upload(base, job_id):
    shutil.rmtree(base / job_id, ignore_errors=True)
    with connection(base, write=True) as conn:
        conn.execute("DELETE FROM jobs WHERE id=? AND status='staging'", (job_id,))


def recover(base):
    with connection(base, write=True) as conn:
        conn.execute("UPDATE jobs SET status='queued', stage='queued', detail=NULL, updated=? WHERE status='running'", (time.time(),))


def claim(base):
    with connection(base, write=True) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY seq LIMIT 1").fetchone()
        if row:
            conn.execute(
                "UPDATE jobs SET status='running', stage='preparing_model', updated=? WHERE id=?",
                (time.time(), row["id"]),
            )
    return dict(row) if row else None


def update(base, job_id, stage, *, detail=None, result=None, error=None):
    now = time.time()
    finished = stage in ("completed", "failed")
    with connection(base, write=True) as conn:
        conn.execute(
            """UPDATE jobs SET stage=?, detail=?, updated=?, result_json=coalesce(?, result_json),
               status=?, error=?, finished=? WHERE id=? AND status='running'""",
            (stage, detail, now, json.dumps(result) if result is not None else None,
             stage if finished else "running", error, now if finished else None, job_id),
        )


def trim(base, job_id):
    stored = sum(file.stat().st_size for file in (base / job_id).rglob("*") if file.is_file())
    with connection(base, write=True) as conn:
        conn.execute("UPDATE jobs SET reserved=? WHERE id=?", (stored, job_id))


def expire(base):
    now = time.time()
    with connection(base, write=True) as conn:
        expired = conn.execute(
            "SELECT id FROM jobs WHERE finished < ? OR (status='staging' AND updated < ?)",
            (now - RETENTION_SECONDS, now - 900),
        ).fetchall()
        for row in expired:
            workspace = base / row["id"]
            if workspace.is_dir():
                shutil.rmtree(workspace)
            conn.execute("DELETE FROM jobs WHERE id=?", (row["id"],))


def get_jobs(base, *, user_id, sign_in=None, job_id=None, run_mode=None):
    sql = """SELECT j.*, (SELECT count(*) FROM jobs q WHERE q.status='queued' AND q.seq<j.seq) AS ahead
             FROM jobs j WHERE j.user_id=? AND j.status!='staging'"""
    args = [user_id]
    if sign_in is not None:
        sql += " AND j.sign_in=?"
        args.append(sign_in)
    if job_id is not None:
        sql += " AND j.id=?"
        args.append(job_id)
    if run_mode is not None:
        sql += " AND coalesce(json_extract(j.input_json, '$.run_mode'), 'sandbox')=?"
        args.append(run_mode)
    with connection(base) as conn:
        return [dict(row) for row in conn.execute(sql + " ORDER BY j.seq DESC LIMIT 20", args)]


def serialize(job):
    data = json.loads(job["result_json"])
    parameters = json.loads(job["input_json"])
    data.setdefault("title", (data.get("draft") or {}).get("title") or parameters.get("title"))
    if parameters.get("practice_sample_id"):
        data.setdefault("sample_id", parameters["practice_sample_id"])
    fields = ("id", "status", "stage", "detail", "error", "created", "updated")
    return {**data, **{field: job[field] for field in fields},
            "run_mode": parameters.get("run_mode", "sandbox"),
            "model_count": parameters.get("model_count", 1),
            "ahead": job["ahead"] if job["status"] == "queued" else None,
            "position": job["ahead"] + 1 if job["status"] == "queued" else None}
