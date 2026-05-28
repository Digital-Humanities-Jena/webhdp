import requests
import time
import os
import random
import string
import pytest

BASE_URL = "http://localhost:8000"


def require_live_service():
    try:
        requests.get(BASE_URL, timeout=0.5)
    except requests.RequestException as exc:
        pytest.skip(f"live HPC-Link service is not available at {BASE_URL}: {exc}")

def test_file_operations():
    require_live_service()
    print(f"Testing against {BASE_URL}")

    # 0. Setup test path
    # We'll use a likely safe path, or try to discovery home
    # Assuming standard HPC home structure or just use /tmp if possible, but SFTP might be chrooted or relative
    # Let's assume relative to home for SSH user
    base_test_path = "hpc_link_test_files"

    # 1. Test Mkdir
    print("\n--- Testing Mkdir ---")
    try:
        resp = requests.post(f"{BASE_URL}/files/mkdir", json={"path": base_test_path})
        print(f"Mkdir response: {resp.status_code} {resp.json()}")
        if resp.status_code == 409:
            print("Directory already exists, proceeding...")
    except Exception as e:
        print(f"Mkdir failed: {e}")

    # 2. Test List
    print("\n--- Testing List ---")
    resp = requests.get(f"{BASE_URL}/files/list", params={"path": base_test_path})
    print(f"List response: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Entries: {len(data.get('entries', []))}")

    # 3. Test Upload (Chunked)
    print("\n--- Testing Upload ---")
    file_name = f"test_{int(time.time())}.bin"
    remote_path = f"{base_test_path}/{file_name}"

    # Init
    resp = requests.post(f"{BASE_URL}/files/upload/init", json={"path": remote_path})
    print(f"Init upload response: {resp.status_code}")
    if resp.status_code != 200:
        print("Failed to init upload")
        return

    upload_id = resp.json()["upload_id"]
    print(f"Upload ID: {upload_id}")

    # Upload chunks (3 chunks of 1KB)
    total_size = 0
    for i in range(3):
        chunk_data = os.urandom(1024)
        total_size += len(chunk_data)
        resp = requests.put(
            f"{BASE_URL}/files/upload/{upload_id}",
            data=chunk_data
        )
        if resp.status_code != 200:
            print(f"Chunk {i} failed: {resp.status_code}")
            return

    # Finish
    resp = requests.post(f"{BASE_URL}/files/upload/{upload_id}/finish")
    print(f"Finish upload response: {resp.status_code}")

    # 4. Verify Stat
    print("\n--- Testing Stat ---")
    resp = requests.get(f"{BASE_URL}/files/stat", params={"path": remote_path})
    print(f"Stat response: {resp.status_code}")
    if resp.status_code == 200:
        stat_data = resp.json()
        print(f"Size match: {stat_data['size']} == {total_size} -> {stat_data['size'] == total_size}")

    # 5. Test Delete
    print("\n--- Testing Delete ---")
    resp = requests.delete(f"{BASE_URL}/files/", params={"path": remote_path})
    print(f"Delete file response: {resp.status_code}")

    # Verify deletion
    resp = requests.get(f"{BASE_URL}/files/stat", params={"path": remote_path})
    print(f"Stat after delete (should be 404): {resp.status_code}")

    # Cleanup directory
    resp = requests.delete(f"{BASE_URL}/files/", params={"path": base_test_path})
    print(f"Delete dir response: {resp.status_code}")

if __name__ == "__main__":
    test_file_operations()
