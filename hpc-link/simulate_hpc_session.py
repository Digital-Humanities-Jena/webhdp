import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock

# Ensure we can import app
sys.path.append(os.getcwd())

from app.ssh_manager import ssh_manager

# --- MOCK SETUP MUST HAPPEN BEFORE CLIENT INIT IF POSSIBLE,
# BUT SINCE WE PATCH THE SINGLETON INSTANCE, IT'S OKAY AFTER IMPORT TOO ---

# 1. Mock SFTP Entries
class MockAttribute:
    def __init__(self, size, mtime, permissions):
        self.size = size
        self.mtime = mtime
        self.permissions = permissions

class MockEntry:
    def __init__(self, filename, size, mtime, permissions):
        self.filename = filename
        self.attrs = MockAttribute(size, mtime, permissions)

FILE_LISTING = [
    MockEntry("experiments", 4096, 1706090000, 0o40755), # Dir
    MockEntry("dataset_v1.csv", 1024000, 1706091200, 0o100644),
    MockEntry("train.py", 2500, 1706091300, 0o100644),
    MockEntry("slurm-1001.out", 500, 1706091400, 0o100644),
]

# 2. Mock Data
NVIDIA_SMI_OUTPUT = """
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 525.85.12    Driver Version: 525.85.12    CUDA Version: 12.0     |
|-------------------------------+----------------------+----------------------|
|   0  NVIDIA A100-PCIE...  On   | 00000000:01:00.0 Off |                    0 |
| N/A   35C    P0    35W / 250W |      0MiB / 40960MiB |      0%      Default |
|                               |                      |             Disabled |
+-------------------------------+----------------------+----------------------+
"""

SQUEUE_RUNNING = "1001|deep-learning-job|partition-a|RUNNING|0:42|1|None"
SBATCH_OUTPUT = "Submitted batch job 1001"
SCONTROL_OUTPUT = "JobId=1001 Name=deep-learning-job WorkDir=/srv/hpc-link/data StdOut=/srv/hpc-link/data/slurm-1001.out"

# 3. Patch SSHManager Methods
mock_sftp = AsyncMock()
mock_sftp.readdir.return_value = FILE_LISTING
mock_sftp.stat.return_value = MockAttribute(4096, 1706090000, 0o40755) # Default to dir stat
mock_sftp.exists.return_value = True

# FIX: sftp.open needs to be a MagicMock that returns an Async Context Manager
mock_file_handle = AsyncMock()
mock_file_ctx = AsyncMock()
mock_file_ctx.__aenter__.return_value = mock_file_handle
mock_sftp.open = MagicMock(return_value=mock_file_ctx)

mock_conn_ctx = AsyncMock()
mock_conn_ctx.__aenter__.return_value = mock_sftp

ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)
ssh_manager.connect = AsyncMock()
ssh_manager.is_connected = AsyncMock(return_value=True)
ssh_manager.get_hostname = AsyncMock(return_value="hpc-login.example.edu")

async def mock_run_command(command, timeout=60.0):
    if "nvidia-smi" in command:
        return NVIDIA_SMI_OUTPUT, "", 0
    elif "sbatch" in command:
        return SBATCH_OUTPUT, "", 0
    elif "squeue" in command:
        return SQUEUE_RUNNING, "", 0
    elif "scontrol show job" in command:
        return SCONTROL_OUTPUT, "", 0
    elif "hostname" in command:
        return "hpc-login-node", "", 0
    return "", f"Command '{command}' not mocked", 1

ssh_manager.run_command = AsyncMock(side_effect=mock_run_command)

# --- INIT CLIENT ---
from fastapi.testclient import TestClient
from app.main import app
from app.config import get_settings
from unittest.mock import patch

client = TestClient(app)
# Default headers for all requests
client.headers = {"X-API-Key": "simulation-secret"}

def print_header(text):
    print(f"\n\033[1;36m{'='*60}\033[0m")
    print(f"\033[1;36m{text.center(60)}\033[0m")
    print(f"\033[1;36m{'='*60}\033[0m")

def print_info(key, value):
    print(f"\033[1;32m{key:<20}\033[0m : {value}")

def _run_simulation_logic():
    print_header("HPC LINK APPLICATION - CAPABILITY DEMO")

    # 1. Connectivity
    print("\n--- 1. Connectivity Check ---")
    res = client.get("/api/health/ssh")
    if res.status_code == 200:
        data = res.json()
        print_info("SSH Connection", "Active" if data['connected'] else "Inactive")
        print_info("Connected Node", data['hostname'])
    else:
        print("Connectivity check failed:", res.text)

    # 2. Filesystem
    print("\n--- 2. Remote Filesystem Browser ---")
    path = "/srv/hpc-link/data"
    print_info("Listing Directory", path)
    res = client.get(f"/api/files/list?path={path}")
    if res.status_code == 200:
        entries = res.json()['entries']
        print(f"\n{'Permission':<12} {'Size':<10} {'Name'}")
        print("-" * 40)
        for e in entries:
            icon = "📁" if e['is_dir'] else "📄"
            print(f"{e['permissions']:<12} {str(e['size']):<10} {icon} {e['name']}")
    else:
        print("Error listing files:", res.text)

    # 3. Hardware Info
    print("\n--- 3. Hardware Introspection ---")
    res = client.get("/api/hpc/nvidia-smi")
    if res.status_code == 200:
        gpu = res.json()
        print_info("GPU Detected", gpu['gpu_name'])
        print_info("VRAM Usage", gpu['gpu_memory'])

    # 4. Job Submission
    print("\n--- 4. Job Submission Workflow ---")
    job_payload = {
        "job_name": "deep-learning-job",
        "working_dir": "/srv/hpc-link/data",
        "commands": ["uv run train.py --epochs 100"],
        "gpu_count": 1,
        "partition": "partition-a"
    }
    print(f"Submitting Job: {job_payload['job_name']}")
    print(f"Command: {job_payload['commands'][0]}")

    res = client.post("/api/jobs/submit", json=job_payload)
    if res.status_code == 200:
        job_res = res.json()
        job_id = job_res['job_id']
        print_info("Submission Status", "SUCCESS")
        print_info("SLURM Job ID", job_id)
        print_info("Script Path", job_res['script_path'])

        # 5. Job Status
        print("\n--- 5. Monitoring Job Status ---")
        res = client.get(f"/api/jobs/{job_id}")
        if res.status_code == 200:
            status = res.json()
            print_info("Current State", status['state'])
            print_info("Time Elapsed", status['time_used'])
            print_info("Partition", status['partition'])
        else:
             print("Status check failed:", res.text)

    else:
        print("Job Submission Failed:", res.text)

    print("\n")

def run_simulation():
    # Patch settings in app.security where get_api_key uses it
    with patch("app.security.get_settings") as mock_settings:
        mock_settings.return_value.api_key = "simulation-secret"
        mock_settings.return_value.hpc_data_root = "/srv/hpc-link/data"
        _run_simulation_logic()


if __name__ == "__main__":
    run_simulation()
