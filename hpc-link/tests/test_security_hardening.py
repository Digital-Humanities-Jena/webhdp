import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from fastapi import Request
from fastapi.testclient import TestClient
from app.auth_store import AuthenticatedUser
from app.main import app
from app.limiter import limiter
from app.schemas.apps import WebHdpSessionCreateResponse
from app.security import get_api_key


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

class TestSecurityHardening(unittest.TestCase):
    def setUp(self):
        # Reset limiter storage
        limiter.reset()
        self.client = TestClient(app)

    @patch('app.security.get_settings')
    def test_api_key_enforcement(self, mock_settings):
        # 0. Test Secure Default (No Key Set) -> Should Fail
        mock_settings.return_value.api_key = None
        mock_settings.return_value.legacy_api_key_auth_enabled = True
        mock_settings.return_value.hpc_data_root = "/tmp"

        response = self.client.get("/api/apps", headers={"X-API-Key": "secret-key"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("API Key not set", response.json()["detail"])

        # Enable API Key for remaining tests
        mock_settings.return_value.api_key = "secret-key"

        # 1. Request without key -> 403
        response = self.client.get("/api/apps")
        self.assertEqual(response.status_code, 403)

        # 2. Request with wrong key -> 403
        response = self.client.get("/api/apps", headers={"X-API-Key": "wrong-key"})
        self.assertEqual(response.status_code, 403)

        with patch('app.routers.apps.hpc_application_service.list_applications', new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []

            # 3. Request with correct Header works only on allowed service paths.
            response = self.client.get("/api/apps", headers={"X-API-Key": "secret-key"})
            self.assertEqual(response.status_code, 200)

            # 4. Query parameter auth is intentionally disabled
            response = self.client.get("/api/apps?api_key=secret-key")
            self.assertEqual(response.status_code, 403)

            # 5. Legacy API key no longer authenticates general HPC endpoints.
            response = self.client.get("/api/hpc/partitions", headers={"X-API-Key": "secret-key"})
            self.assertEqual(response.status_code, 403)
            self.assertIn("limited to WebHDP", response.json()["detail"])

            # 6. Legacy API key cannot reach admin WebHDP component-management paths.
            response = self.client.post(
                "/api/apps/webhdp/components/install",
                headers={"X-API-Key": "secret-key"},
                json={},
            )
            self.assertEqual(response.status_code, 403)
            self.assertIn("limited to WebHDP", response.json()["detail"])

    @patch('app.security.get_settings')
    def test_legacy_key_authenticates_only_the_exact_allocation_recovery_routes(self, mock_settings):
        mock_settings.return_value.api_key = "test-recovery-key"
        mock_settings.return_value.legacy_api_key_auth_enabled = True
        mock_settings.return_value.legacy_api_key_allowed_partitions = ["gpu"]
        headers = {"X-API-Key": "test-recovery-key"}
        path = "/api/apps/webhdp/sessions/requests"
        request_id = str(uuid4())
        now = datetime.now(timezone.utc)
        session = WebHdpSessionCreateResponse(
            session_id=request_id, app_id="webhdp", job_id="12345", partition="gpu", gpu_count=1,
            remote_session_dir="/work/session", input_dir="/work/session/inputs", output_dir="/work/session/outputs",
            status="queued", created_at=now, expires_at=now,
        )
        service = "app.routers.apps.hpc_application_service"

        with (patch(f"{service}.create_webhdp_session", new_callable=AsyncMock, return_value=session) as submit,
              patch(f"{service}.get_webhdp_session_request", new_callable=AsyncMock, return_value=session) as recover):
            self.assertEqual(self.client.post(path, json={"request_id": request_id, "partition": "gpu"},
                                              headers=headers).status_code, 200)
            self.assertEqual(self.client.get(f"{path}/{request_id}", headers=headers).status_code, 200)
            self.assertEqual(self.client.get(f"{path}/not-a-uuid", headers=headers).status_code, 403)
            self.assertEqual(self.client.get(f"{path}/{request_id}").status_code, 403)

        submit.assert_awaited_once()
        recover.assert_awaited_once()
        principal = submit.call_args.args[1]
        self.assertEqual(principal.username, "service-api-key")
        self.assertFalse(principal.is_admin)
        self.assertEqual(principal.allowed_partitions, ["gpu"])
        self.assertEqual(recover.call_args.args, (request_id, principal))

    @patch('app.security.get_settings')
    def test_health_check_bypass(self, mock_settings):
        # API Key enabled
        mock_settings.return_value.api_key = "secret-key"

        # Health check should still work without key
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    @patch('app.security.get_settings')
    def test_rate_limiting(self, mock_settings):
        app.dependency_overrides[get_api_key] = install_admin_auth
        self.addCleanup(lambda: app.dependency_overrides.pop(get_api_key, None))

        # Configure API Key
        mock_settings.return_value.api_key = "limit-key"

        # We need to ensure limiter is enabled and working.
        # slowapi stores limit info in redis or memory. Memory is default.
        # We need to mock the limiter or just spam requests.

        # Note: TestClient in FastAPI < 0.100 sometimes has issues with client host?
        # slowapi uses get_remote_address. TestClient requests usually have "testclient" as host.

        # We applied 10/minute on /api/hpc/execute

        headers = {"X-API-Key": "limit-key"}

        # We need to patch ssh_manager to avoid delays/errors
        with patch('app.routers.hpc.ssh_manager.run_command') as mock_run:
            mock_run.return_value = ("ok", "", 0)

            # Make 10 allowed requests
            for _ in range(10):
                response = self.client.post(
                    "/api/hpc/execute",
                    json={"command": "echo 1"},
                    headers=headers
                )
                self.assertEqual(response.status_code, 200)

            # 11th request should be 429
            response = self.client.post(
                "/api/hpc/execute",
                json={"command": "echo 1"},
                headers=headers
            )
            self.assertEqual(response.status_code, 429)

    def test_cors_headers(self):
        response = self.client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET"
            }
        )
        self.assertEqual(response.status_code, 200)
        # With allow_credentials=True, Starlette mirrors the origin
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
