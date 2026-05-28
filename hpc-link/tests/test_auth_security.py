import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.routers.auth import _login_attempts, _login_lockouts


class TestAuthSecurity(unittest.TestCase):
    def setUp(self):
        _login_attempts.clear()
        _login_lockouts.clear()
        self.client = TestClient(app)

    def tearDown(self):
        _login_attempts.clear()
        _login_lockouts.clear()

    @patch("app.routers.auth.get_settings")
    @patch("app.routers.auth.auth_store.authenticate")
    def test_login_lockout_after_repeated_failures(self, mock_authenticate, mock_settings):
        mock_settings.return_value.login_max_attempts_per_window = 2
        mock_settings.return_value.login_attempt_window_seconds = 300
        mock_settings.return_value.login_lockout_seconds = 60
        mock_settings.return_value.auth_token_secret = "test-secret"
        mock_settings.return_value.auth_token_ttl_minutes = 60
        mock_authenticate.return_value = None

        payload = {"username": "does-not-exist", "password": "bad-password"}

        first = self.client.post("/api/auth/login", json=payload)
        second = self.client.post("/api/auth/login", json=payload)
        third = self.client.post("/api/auth/login", json=payload)

        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(third.status_code, 429)
        self.assertIn("Too many failed login attempts", third.json()["detail"])
        self.assertIn("Retry-After", third.headers)


if __name__ == "__main__":
    unittest.main()
