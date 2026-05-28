import unittest
from fastapi import HTTPException
from app.security import (
    _extract_ws_bearer_token,
    enforce_allocation_policy,
    get_request_user,
    get_ws_request_user,
    validate_path,
    validate_slurm_resource_token,
)
from app.auth_store import AuthenticatedUser
from unittest.mock import patch
from types import SimpleNamespace

class TestSecurity(unittest.TestCase):

    @patch('app.security.get_settings')
    def test_validate_path_valid(self, mock_get_settings):
        mock_get_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # Relative path
        path = "sub/file.txt"
        validated = validate_path(path)
        self.assertEqual(validated, "/srv/hpc-link/data/sub/file.txt")

        # Absolute path within base
        path = "/srv/hpc-link/data/another/file.txt"
        validated = validate_path(path)
        self.assertEqual(validated, "/srv/hpc-link/data/another/file.txt")

    @patch('app.security.get_settings')
    def test_validate_path_traversal(self, mock_get_settings):
        mock_get_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # Traversal attempt
        path = "../passwd"
        with self.assertRaises(HTTPException) as cm:
            validate_path(path)
        self.assertEqual(cm.exception.status_code, 403)

        # Absolute outside base
        path = "/etc/passwd"
        with self.assertRaises(HTTPException) as cm:
            validate_path(path)
        self.assertEqual(cm.exception.status_code, 403)

        # Prefix collision attempt
        path = "/srv/hpc-link/data_evil/escape.txt"
        with self.assertRaises(HTTPException) as cm:
            validate_path(path)
        self.assertEqual(cm.exception.status_code, 403)

    @patch('app.security.get_settings')
    def test_validate_path_normalization(self, mock_get_settings):
        mock_get_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # Traversal back into base (logically)
        # /srv/hpc-link/data/sub/../../data/file.txt
        # normalized should be /srv/hpc-link/data/file.txt
        path = "sub/../../data/file.txt"
        validated = validate_path(path)
        self.assertEqual(validated, "/srv/hpc-link/data/file.txt")

    def test_ws_bearer_token_extraction(self):
        ws = SimpleNamespace(
            headers={"authorization": "Bearer abc123"},
            query_params={},
        )
        self.assertEqual(_extract_ws_bearer_token(ws, allow_query_token=False), "abc123")

        ws = SimpleNamespace(
            headers={"sec-websocket-protocol": "hpc-link-v1, bearer.token-from-proto"},
            query_params={},
        )
        self.assertEqual(
            _extract_ws_bearer_token(ws, allow_query_token=False),
            "token-from-proto",
        )

        ws = SimpleNamespace(headers={}, query_params={"token": "query-token"})
        self.assertIsNone(_extract_ws_bearer_token(ws, allow_query_token=False))
        self.assertEqual(
            _extract_ws_bearer_token(ws, allow_query_token=True),
            "query-token",
        )

    def test_slurm_resource_token_rejects_shell_syntax(self):
        with self.assertRaises(HTTPException) as cm:
            validate_slurm_resource_token("a100;touch /tmp/pwned", "GPU type")
        self.assertEqual(cm.exception.status_code, 400)

    def test_missing_auth_context_fails_closed(self):
        request = SimpleNamespace(state=SimpleNamespace())
        websocket = SimpleNamespace(state=SimpleNamespace())

        with self.assertRaises(HTTPException) as request_context:
            get_request_user(request)
        self.assertEqual(request_context.exception.status_code, 401)

        with self.assertRaises(HTTPException) as websocket_context:
            get_ws_request_user(websocket)
        self.assertEqual(websocket_context.exception.status_code, 401)

    def test_non_admin_empty_gpu_type_policy_is_not_unrestricted(self):
        user = AuthenticatedUser(
            user_id=1,
            username="demo",
            is_admin=False,
            invited=True,
            is_active=True,
            allowed_partitions=["partition-a"],
            allowed_gpu_types=[],
            max_duration_minutes=30,
            max_gpu_count=1,
        )
        with self.assertRaises(HTTPException) as cm:
            enforce_allocation_policy(
                user,
                partition="partition-a",
                gpu_type="a100",
                gpu_count=1,
                duration_minutes=10,
            )
        self.assertEqual(cm.exception.status_code, 403)

if __name__ == '__main__':
    unittest.main()
