import requests
import json
import os
import time
import sys
import zipfile
import io

# Configuration
BASE_URL = "http://localhost:8080/api/v1"
AUTH_URL = f"{BASE_URL}/auth/login"
PIPELINES_URL = f"{BASE_URL}/pipelines"
PIPELINE_ID = "full_workflow"

# Credentials
USERNAME = "admin@hdp.com"
PASSWORD = "test123+#"

# Test File
TEST_FILE_PATH = "test_models/site042_structure_main.fbx"

def login():
    print(f"Logging in as {USERNAME}...")
    resp = requests.post(AUTH_URL, json={"email": USERNAME, "password": PASSWORD})
    if resp.status_code != 200:
        print(f"Login failed: {resp.text}")
        sys.exit(1)
    return resp.json()["data"]["access_token"]

def create_session(token):
    print("Creating session with ZIP scan...")
    headers = {"Authorization": f"Bearer {token}"}

    if not os.path.exists(TEST_FILE_PATH):
        print(f"Test file not found: {TEST_FILE_PATH}")
        sys.exit(1)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.write(TEST_FILE_PATH, os.path.basename(TEST_FILE_PATH))
    zip_buffer.seek(0)

    msf_content = "filename,title,description\n"
    msf_content += f"{os.path.basename(TEST_FILE_PATH)},Test Model,A test description\n"

    files = {
        "zip_file": ("test_upload.zip", zip_buffer, "application/zip"),
        "msf_file": ("metadata.csv", msf_content, "text/csv")
    }

    data = {"filename_column": "filename"}

    print("Uploading ZIP and MSF...")
    resp = requests.post(f"{BASE_URL}/sessions/directory", files=files, data=data, headers=headers)

    if resp.status_code != 200:
        print(f"Session creation failed: {resp.text}")
        sys.exit(1)

    resp_data = resp.json()["data"]
    session_id = resp_data["session_id"]

    found_files = resp_data.get("foundFiles", [])
    if not found_files:
        print("No files found in session response?!")
        sys.exit(1)

    target_file = found_files[0]
    if isinstance(target_file, dict):
        file_path = target_file.get("path")
    else:
        file_path = target_file

    print(f"Created Session {session_id}")
    print(f"Target file path on server: {file_path}")

    return session_id, file_path

def run_pipeline(token, session_id, file_path):
    print(f"Running pipeline '{PIPELINE_ID}' on session {session_id}...")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "local_file_paths": [file_path],
        "session_id": session_id,
        "is_sandbox": True
    }

    resp = requests.post(f"{PIPELINES_URL}/{PIPELINE_ID}/execute_on_local_files", json=payload, headers=headers)
    if resp.status_code != 200:
        print(f"Pipeline execution failed: {resp.text}")
        sys.exit(1)

    return resp.json()["data"]

def check_results(execution_data):
    print("\n--- Pipeline Execution Results ---")
    results = execution_data.get("result", {}).get("details", [])

    for item in results:
        file_path = item.get("file_path")
        render_status = item.get("render", {})
        zenodo_status = item.get("zenodo", {})
        edm_status = item.get("edm", {})
        iiif_status = item.get("iiif", {})

        print(f"\nFile: {file_path}")
        print(f"Render Success: {render_status.get('success')}")
        print(f"Render Status: {render_status.get('status')}")

        print(f"Zenodo Draft: {zenodo_status.get('draft_success')}")
        print(f"Zenodo Upload: {zenodo_status.get('upload_success')}")

        print(f"EDM Generated: {edm_status.get('success')}")
        print(f"IIIF Generated: {iiif_status.get('success')}")

        if render_status.get("success"):
            print(">>> RENDER VERIFICATION PASSED")
        else:
            print(f">>> RENDER VERIFICATION FAILED: {render_status.get('error')}")

if __name__ == "__main__":
    try:
        token = login()
        session_id, container_path = create_session(token)

        # Give some time for background tasks if any
        time.sleep(2)

        execution_data = run_pipeline(token, session_id, container_path)
        check_results(execution_data)

    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
