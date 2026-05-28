import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import Request
from fastapi.testclient import TestClient
from app.main import app
from app.security import get_api_key
from app.auth_store import AuthenticatedUser


async def install_admin_auth(request: Request):
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

class TestHealthRouter(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @patch('app.routers.health.ssh_manager')
    def test_ssh_health_connected(self, mock_ssh_manager):
        app.dependency_overrides[get_api_key] = install_admin_auth
        mock_ssh_manager.is_connected = AsyncMock(return_value=True)
        mock_ssh_manager.get_hostname = AsyncMock(return_value="hpc-login-node")
        try:
            response = self.client.get("/api/health/ssh")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["connected"], True)
            self.assertEqual(data["hostname"], "hpc-login-node")
        finally:
            app.dependency_overrides = {}

    @patch('app.routers.health.ssh_manager')
    def test_ssh_health_disconnected(self, mock_ssh_manager):
        app.dependency_overrides[get_api_key] = install_admin_auth
        mock_ssh_manager.is_connected = AsyncMock(return_value=False)
        mock_ssh_manager.connect = AsyncMock()
        mock_ssh_manager.get_hostname = AsyncMock(return_value="hpc-login-node")
        try:
            response = self.client.get("/api/health/ssh")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["connected"], True)
            mock_ssh_manager.connect.assert_called_once()
        finally:
            app.dependency_overrides = {}

    @patch('app.routers.health.ssh_manager')
    def test_jump_host_health_localhost(self, mock_ssh_manager):
        app.dependency_overrides[get_api_key] = install_admin_auth
        mock_ssh_manager.is_connected = AsyncMock(return_value=True)
        mock_ssh_manager.get_hostname = AsyncMock(return_value="hpc-login-node")

        try:
            response = self.client.get("/api/health/jump?target=localhost")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["can_reach_target"], True)
            self.assertEqual(data["target_host"], "login_node")
        finally:
            app.dependency_overrides = {}

if __name__ == '__main__':
    unittest.main()
