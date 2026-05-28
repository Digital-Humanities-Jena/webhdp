import unittest
from unittest.mock import AsyncMock, patch
from fastapi import Request
from fastapi.testclient import TestClient
from app.main import app
from app.limiter import limiter
from app.security import get_api_key
from app.auth_store import AuthenticatedUser

class TestHPCRouter(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        async def test_auth(request: Request):
            request.state.current_user = AuthenticatedUser(
                user_id=1,
                username="admin",
                is_admin=True,
                invited=True,
                is_active=True,
                allowed_partitions=[],
                allowed_gpu_types=[],
                max_duration_minutes=10080,
                max_gpu_count=16,
            )
            return "test-key"

        app.dependency_overrides[get_api_key] = test_auth
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = {}

    @patch('app.routers.hpc.ssh_manager')
    def test_execute_command(self, mock_ssh_manager):
        mock_ssh_manager.run_command = AsyncMock(return_value=("hello", "", 0))

        response = self.client.post("/api/hpc/execute", json={"command": "echo hello"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["stdout"], "hello")
        self.assertEqual(data["success"], True)

    @patch('app.routers.hpc.get_request_user')
    @patch('app.routers.hpc.ssh_manager')
    def test_execute_command_forbidden_for_non_admin(self, mock_ssh_manager, mock_get_request_user):
        mock_ssh_manager.run_command = AsyncMock(return_value=("hello", "", 0))
        mock_get_request_user.return_value = AuthenticatedUser(
            user_id=101,
            username="demo",
            is_admin=False,
            invited=True,
            is_active=True,
            allowed_partitions=["partition-a"],
            allowed_gpu_types=[],
            max_duration_minutes=30,
            max_gpu_count=1,
        )

        response = self.client.post("/api/hpc/execute", json={"command": "echo hello"})
        self.assertEqual(response.status_code, 403)
        mock_ssh_manager.run_command.assert_not_called()

    @patch('app.routers.hpc.ssh_manager')
    def test_allocate_gpu(self, mock_ssh_manager):
        mock_ssh_manager.allocate_gpu_and_run = AsyncMock(return_value=("gpu_out", "", 0))

        payload = {
            "command": "nvidia-smi",
            "partition": "partition-a",
            "gpu_count": 1
        }
        response = self.client.post("/api/hpc/allocate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["stdout"], "gpu_out")

        mock_ssh_manager.allocate_gpu_and_run.assert_called_with(
            command="nvidia-smi",
            partition="partition-a",
            gpu_type="accelerator-a",
            gpu_count=1,
            time_limit="00:10:00",
            timeout=300.0
        )

    @patch('app.routers.hpc.get_request_user')
    @patch('app.routers.hpc.ssh_manager')
    def test_allocate_gpu_forbidden_for_non_admin(self, mock_ssh_manager, mock_get_request_user):
        mock_ssh_manager.allocate_gpu_and_run = AsyncMock(return_value=("gpu_out", "", 0))
        mock_get_request_user.return_value = AuthenticatedUser(
            user_id=102,
            username="demo",
            is_admin=False,
            invited=True,
            is_active=True,
            allowed_partitions=["partition-a"],
            allowed_gpu_types=[],
            max_duration_minutes=30,
            max_gpu_count=1,
        )

        response = self.client.post(
            "/api/hpc/allocate",
            json={"command": "nvidia-smi", "partition": "partition-a", "gpu_count": 1},
        )

        self.assertEqual(response.status_code, 403)
        mock_ssh_manager.allocate_gpu_and_run.assert_not_called()

    @patch('app.routers.hpc.ssh_manager')
    def test_nvidia_smi(self, mock_ssh_manager):
        nvidia_out = """
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 525.85.12    Driver Version: 525.85.12    CUDA Version: 12.0     |
|-------------------------------+----------------------+----------------------+
|   0  NVIDIA A100-PCIE...  On   | 00000000:01:00.0 Off |                    0 |
| N/A   35C    P0    35W / 250W |      0MiB / 40960MiB |      0%      Default |
|                               |                      |             Disabled |
+-------------------------------+----------------------+----------------------+
"""
        mock_ssh_manager.allocate_gpu_and_run = AsyncMock(return_value=(nvidia_out, "", 0))

        response = self.client.get("/api/hpc/nvidia-smi?partition=partition-b")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["success"], True)
        self.assertEqual(data["gpu_name"], "NVIDIA A100-PCIE...")
        self.assertEqual(data["gpu_memory"], "0MiB / 40960MiB")

    @patch('app.routers.hpc.ssh_manager')
    def test_list_partitions(self, mock_ssh_manager):
        sinfo_out = "partition-b|node01|up|1|gpu:a100:1|idle\npartition-a|node02|up|2|gpu:rtx3090:2|allocated"
        mock_ssh_manager.run_command = AsyncMock(return_value=(sinfo_out, "", 0))

        response = self.client.get("/api/hpc/partitions")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["partitions"]), 2)
        self.assertEqual(data["partitions"][0]["partition"], "partition-b")
        self.assertEqual(data["partitions"][1]["partition"], "partition-a")

if __name__ == '__main__':
    unittest.main()
