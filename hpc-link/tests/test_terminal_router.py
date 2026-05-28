import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import app
from app.security import get_ws_api_key
from app.auth_store import AuthenticatedUser
import json

class TestTerminalRouter(unittest.TestCase):
    def setUp(self):
        async def test_ws_auth(websocket: WebSocket):
            websocket.state.current_user = AuthenticatedUser(
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

        app.dependency_overrides[get_ws_api_key] = test_ws_auth
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = {}

    @patch('app.routers.terminal.ssh_manager')
    def test_terminal_websocket_mock(self, mock_ssh_manager):
        # Force mock_hpc = True via settings patch if needed,
        # or rely on fallback if ssh_manager fails.
        # Let's patch get_settings to return mock_hpc=True
        with patch('app.routers.terminal.get_settings') as mock_settings:
            mock_settings.return_value.mock_hpc = True
            mock_settings.return_value.terminal_cols = 80
            mock_settings.return_value.terminal_rows = 24
            mock_settings.return_value.terminal_timeout_seconds = 60

            with self.client.websocket_connect("/api/ws/terminal") as websocket:
                # Receive initial mock messages
                msg1 = websocket.receive_bytes()
                self.assertIn(b"MOCK TERMINAL", msg1)

                msg2 = websocket.receive_bytes()
                self.assertIn(b"Mock session", msg2)

                msg3 = websocket.receive_bytes()
                self.assertEqual(msg3, b"$ ")

                # Send some input
                websocket.send_bytes(b"l")
                websocket.send_bytes(b"s")
                websocket.send_bytes(b"\r")

                # Receive echo (l)
                echo_l = websocket.receive_bytes()
                self.assertEqual(echo_l, b"l")

                # Receive echo (s)
                echo_s = websocket.receive_bytes()
                self.assertEqual(echo_s, b"s")

                # Receive prompt echo
                prompt = websocket.receive_bytes()
                self.assertEqual(prompt, b"\r\n$ ")

    @patch('app.routers.terminal.ssh_manager')
    def test_terminal_websocket_ssh(self, mock_ssh_manager):
        # Mock SSH process
        mock_process = MagicMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b"output", b""])
        mock_process.stdin.write = MagicMock()

        mock_ssh_manager.start_shell_session = AsyncMock(return_value=mock_process)
        mock_ssh_manager.resize_terminal = AsyncMock()

        with patch('app.routers.terminal.get_settings') as mock_settings:
            mock_settings.return_value.mock_hpc = False
            mock_settings.return_value.terminal_cols = 80
            mock_settings.return_value.terminal_rows = 24
            mock_settings.return_value.terminal_timeout_seconds = 60

            with self.client.websocket_connect("/api/ws/terminal") as websocket:
                # Should receive "output"
                msg = websocket.receive_bytes()
                self.assertEqual(msg, b"output")

                # Send input
                websocket.send_bytes(b"input")
                # Allow time for server to process input
                import time
                time.sleep(0.1)
                mock_process.stdin.write.assert_called_with(b"input")

                # Resize
                websocket.send_text(json.dumps({"type": "resize", "cols": 100, "rows": 40}))
                # Wait a bit for async resize
                import time
                time.sleep(0.1)
                mock_ssh_manager.resize_terminal.assert_called_with(mock_process, 100, 40)

    @patch('app.routers.terminal.get_ws_request_user')
    def test_terminal_websocket_forbidden_for_non_admin(self, mock_get_ws_request_user):
        mock_get_ws_request_user.return_value = AuthenticatedUser(
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

        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect("/api/ws/terminal"):
                pass

        self.assertEqual(cm.exception.code, 1008)

if __name__ == '__main__':
    unittest.main()
