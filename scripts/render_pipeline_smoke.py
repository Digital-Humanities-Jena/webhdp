"""Manual smoke test for the native render pipeline."""

from __future__ import annotations

import io
import os
import sqlite3
import sys
import time
import zipfile

import requests


BASE_URL = os.environ.get("WEBHDP_BASE_URL", "http://localhost:8080/api/v1")
AUTH_URL = f"{BASE_URL}/auth/login"
PIPELINE_ID = os.environ.get("WEBHDP_PIPELINE_ID", "render")
USERNAME = os.environ.get("WEBHDP_USERNAME")
PASSWORD = os.environ.get("WEBHDP_PASSWORD")
TEST_FILE_PATH = os.environ.get("WEBHDP_TEST_MODEL", "test_model.glb")
UPLOAD_TIMEOUT_SECONDS = int(os.environ.get("WEBHDP_UPLOAD_TIMEOUT", "600"))
POLL_INTERVAL_SECONDS = float(os.environ.get("WEBHDP_POLL_INTERVAL", "2"))
LOCAL_DB_PATH = os.environ.get("WEBHDP_DB_PATH", "instance/hdp_web.db")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def login() -> str:
    if not USERNAME or not PASSWORD:
        fail("Set WEBHDP_USERNAME and WEBHDP_PASSWORD before running this smoke test.")
    response = requests.post(AUTH_URL, json={"email": USERNAME, "password": PASSWORD}, timeout=30)
    if response.status_code != 200:
        fail(f"Login failed: {response.text}")
    return response.json()["data"]["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_session(token: str, session_id: int) -> dict:
    response = requests.get(
        f"{BASE_URL}/sessions/{session_id}",
        headers=_auth_headers(token),
        timeout=30,
    )
    if response.status_code != 200:
        fail(f"Failed to fetch session {session_id}: {response.text}")
    return response.json()["data"]


def get_task_status(token: str, task_id: str) -> dict:
    response = requests.get(
        f"{BASE_URL}/sessions/tasks/{task_id}",
        headers=_auth_headers(token),
        timeout=30,
    )
    if response.status_code != 200:
        fail(f"Failed to fetch upload task {task_id}: {response.text}")
    return response.json()["data"]


def get_session_records(token: str, session_id: int) -> list[dict]:
    response = requests.get(
        f"{BASE_URL}/sessions/{session_id}/records",
        headers=_auth_headers(token),
        timeout=60,
    )
    if response.status_code != 200:
        return []

    payload = response.json().get("data", {})
    records = payload.get("records")
    return records if isinstance(records, list) else []


def get_local_session_file_path(session_id: int) -> str | None:
    if not LOCAL_DB_PATH or not os.path.exists(LOCAL_DB_PATH):
        return None

    connection = sqlite3.connect(LOCAL_DB_PATH)
    try:
        row = connection.execute(
            "SELECT path FROM files WHERE session_id = ? ORDER BY id ASC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        connection.close()

    if not row or not row[0]:
        return None
    return str(row[0]).strip() or None


def wait_for_session_file(token: str, session_id: int, task_id: str | None) -> str:
    deadline = time.time() + UPLOAD_TIMEOUT_SECONDS
    last_status = None

    while time.time() < deadline:
        session = get_session(token, session_id)
        records = get_session_records(token, session_id)

        for record in records:
            source_file_path = record.get("source_file_path")
            if isinstance(source_file_path, str) and source_file_path.strip():
                return source_file_path.strip()

        local_file_path = get_local_session_file_path(session_id)
        if local_file_path:
            return local_file_path

        if task_id:
            task = get_task_status(token, task_id)
            task_state = str(task.get("state") or "").upper()
            if task_state == "FAILURE":
                fail(f"Upload task failed: {task}")

            result = task.get("result")
            if isinstance(result, dict) and result.get("status") == "failed":
                fail(f"Upload coordinator failed: {result}")

            last_status = task.get("status") or session.get("status")
        else:
            last_status = session.get("status")

        time.sleep(POLL_INTERVAL_SECONDS)

    fail(
        f"Timed out waiting for session {session_id} to expose a source file path. "
        f"Last status: {last_status}"
    )


def create_session(token: str) -> tuple[int, str]:
    if not os.path.exists(TEST_FILE_PATH):
        fail(f"Test model not found: {TEST_FILE_PATH}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(TEST_FILE_PATH, os.path.basename(TEST_FILE_PATH))
    zip_buffer.seek(0)

    msf_content = "filename,title,description\n"
    msf_content += f"{os.path.basename(TEST_FILE_PATH)},Smoke Test Model,Smoke test description\n"

    response = requests.post(
        f"{BASE_URL}/sessions/directory",
        headers=_auth_headers(token),
        files={
            "zip_file": ("smoke_upload.zip", zip_buffer, "application/zip"),
            "msf_file": ("smoke_metadata.csv", msf_content, "text/csv"),
        },
        data={"filename_column": "filename"},
        timeout=120,
    )
    if response.status_code < 200 or response.status_code >= 300:
        fail(f"Session creation failed: {response.text}")
    payload = response.json()["data"]
    session_id = payload["session_id"]
    found_files = payload.get("foundFiles") or []
    if found_files:
        file_entry = found_files[0]
        file_path = file_entry.get("path") if isinstance(file_entry, dict) else str(file_entry)
        if file_path:
            return session_id, file_path

    task_id = payload.get("task_id")
    return session_id, wait_for_session_file(token, session_id, task_id)


def execute_render(token: str, session_id: int, file_path: str) -> dict:
    response = requests.post(
        f"{BASE_URL}/pipelines/{PIPELINE_ID}/execute_on_local_files",
        headers=_auth_headers(token),
        json={
            "session_id": session_id,
            "local_file_paths": [file_path],
            "is_sandbox": True,
        },
        timeout=1800,
    )
    if response.status_code != 200:
        fail(f"Pipeline execution failed: {response.text}")
    return response.json()["data"]


def main() -> None:
    token = login()
    session_id, file_path = create_session(token)
    time.sleep(2)
    result = execute_render(token, session_id, file_path)

    details = result.get("result", {}).get("details", [])
    if not details:
        fail(f"Native render pipeline returned no details: {result}")
    item = details[0]
    render_status = item.get("render", {})
    print(f"Run ID: {result.get('result', {}).get('run_id')}")
    print(f"Pipeline Version: {result.get('result', {}).get('pipeline_version')}")
    print(f"Render success: {render_status.get('success')}")
    print(f"USDZ success: {item.get('usdz', {}).get('success')}")
    print(f"EDM success: {item.get('edm', {}).get('success')}")
    print(f"IIIF success: {item.get('iiif', {}).get('success')}")
    print(f"METS success: {item.get('mets', {}).get('success')}")

    if not render_status.get("success"):
        fail(f"Render verification failed: {render_status}")


if __name__ == "__main__":
    main()
