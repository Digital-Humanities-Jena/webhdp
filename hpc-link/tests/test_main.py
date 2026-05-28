import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import _validate_startup_security, app

class TestMain(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_root(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("name", data)
        self.assertIn("version", data)
        self.assertEqual(data["docs"], "/docs")

    def test_metrics(self):
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 401)

    @patch("app.main.get_settings")
    def test_startup_validation_blocks_insecure_production_defaults(self, mock_get_settings):
        mock_get_settings.return_value.environment = "production"
        mock_get_settings.return_value.auth_token_secret = "change-me-in-production"
        mock_get_settings.return_value.admin_password = "change-me-admin-password"
        mock_get_settings.return_value.legacy_api_key_auth_enabled = False
        mock_get_settings.return_value.cors_origins = ["http://localhost:5173"]

        with self.assertRaises(RuntimeError):
            _validate_startup_security()

if __name__ == '__main__':
    unittest.main()
