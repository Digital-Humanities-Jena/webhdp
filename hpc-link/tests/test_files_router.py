import unittest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request
from fastapi.testclient import TestClient
from app.main import app
from app.security import get_api_key
from app.auth_store import AuthenticatedUser
from app.routers.files import upload_sessions

class TestFilesRouter(unittest.TestCase):
    def setUp(self):
        # Override auth dependency for tests
        async def test_auth(request: Request):
            request.state.current_user = AuthenticatedUser(
                user_id=1,
                username="service-api-key",
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
        upload_sessions.clear()
        self.client = TestClient(app)

    def tearDown(self):
        upload_sessions.clear()
        app.dependency_overrides = {}

    @patch('app.routers.files.ssh_manager')
    def test_list_directory(self, mock_ssh_manager):
        # Mock SFTP context manager
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp

        # Ensure open_sftp is treated as an async function that returns the context manager
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # Mock readdir return values
        entry1 = MagicMock()
        entry1.filename = "file1.txt"
        entry1.attrs.size = 100
        entry1.attrs.mtime = 123456
        entry1.attrs.permissions = 0o100644

        entry2 = MagicMock()
        entry2.filename = "dir1"
        entry2.attrs.size = 4096
        entry2.attrs.mtime = 123456
        entry2.attrs.permissions = 0o40755

        mock_sftp.readdir.return_value = [entry1, entry2]

        # Mock stat for directory
        dir_attrs = MagicMock()
        dir_attrs.permissions = 0o40755
        mock_sftp.stat.return_value = dir_attrs

        # Use a safe path within default root
        response = self.client.get("/api/files/list?path=/srv/hpc-link/data/tmp")

        if response.status_code != 200:
             print(f"\nList failed: {response.json()}")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['entries']), 2)

    @patch('app.routers.files.ssh_manager')
    def test_upload_flow(self, mock_ssh_manager):
        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # Mock file open context
        mock_file = AsyncMock()
        mock_file_ctx = AsyncMock()
        mock_file_ctx.__aenter__.return_value = mock_file

        mock_sftp.open = MagicMock(return_value=mock_file_ctx)
        mock_sftp.stat.return_value.size = 6

        path = "/srv/hpc-link/data/test.bin"

        # 1. Init
        response = self.client.post("/api/files/upload/init", json={"path": path})
        self.assertEqual(response.status_code, 200)
        upload_id = response.json().get("upload_id")

        # 2. Upload Chunk
        response = self.client.put(
            f"/api/files/upload/{upload_id}",
            content=b"chunk1",
            headers={"Content-Type": "application/octet-stream"}
        )
        self.assertEqual(response.status_code, 200)

        # 3. Finish
        response = self.client.post(f"/api/files/upload/{upload_id}/finish")
        self.assertEqual(response.status_code, 200)

    @patch('app.routers.files.ssh_manager')
    def test_download_full(self, mock_ssh_manager):
        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # Mock Stat (size = 10 bytes)
        mock_sftp.stat.return_value.size = 10

        # Mock File Read
        mock_file = AsyncMock()
        mock_file.read.side_effect = [b"0123456789", b""] # Full content then EOF

        mock_file_ctx = AsyncMock()
        mock_file_ctx.__aenter__.return_value = mock_file
        mock_sftp.open = MagicMock(return_value=mock_file_ctx)

        path = "/srv/hpc-link/data/file.txt"
        response = self.client.get(f"/api/files/download?path={path}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"0123456789")
        self.assertEqual(response.headers["Content-Length"], "10")

    @patch('app.routers.files.ssh_manager')
    def test_download_range(self, mock_ssh_manager):
        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # Mock Stat (size = 10 bytes)
        mock_sftp.stat.return_value.size = 10

        # Mock File Read (Seek then Read)
        mock_file = AsyncMock()
        # Expecting range bytes=2-6 (inclusive) -> 5 bytes, starting at index 2 (b'23456')
        mock_file.read.side_effect = [b"23456", b""]

        mock_file_ctx = AsyncMock()
        mock_file_ctx.__aenter__.return_value = mock_file
        mock_sftp.open = MagicMock(return_value=mock_file_ctx)

        path = "/srv/hpc-link/data/file.txt"
        headers = {"Range": "bytes=2-6"}
        response = self.client.get(f"/api/files/download?path={path}", headers=headers)

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"23456")
        self.assertEqual(response.headers["Content-Length"], "5")
        self.assertEqual(response.headers["Content-Range"], "bytes 2-6/10")

        # Verify seek called
        mock_file.seek.assert_called_with(2)

    def test_security_confinement(self):
        # access outside root
        response = self.client.get("/api/files/list?path=/etc/passwd")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Access denied", response.json()["detail"])

        # traversal attempt
        response = self.client.get("/api/files/list?path=/srv/hpc-link/data/../../etc/passwd")
        # Logic should normalize this outside /srv/hpc-link/data and reject it.
        self.assertEqual(response.status_code, 403)

    @patch('app.routers.files.get_request_user')
    @patch('app.routers.files.ssh_manager')
    def test_non_admin_cannot_access_shared_or_other_user_root(self, mock_ssh_manager, mock_get_request_user):
        mock_get_request_user.return_value = AuthenticatedUser(
            user_id=201,
            username="alice@example.org",
            is_admin=False,
            invited=True,
            is_active=True,
            allowed_partitions=[],
            allowed_gpu_types=[],
            max_duration_minutes=30,
            max_gpu_count=1,
        )

        response = self.client.get("/api/files/list?path=/srv/hpc-link/data/project.dat")

        self.assertEqual(response.status_code, 403)
        mock_ssh_manager.open_sftp.assert_not_called()

    @patch('app.routers.files.get_settings')
    @patch('app.routers.files.get_request_user')
    @patch('app.routers.files.ssh_manager')
    def test_non_admin_default_path_is_namespaced(self, mock_ssh_manager, mock_get_request_user, mock_get_settings):
        mock_get_settings.return_value.hpc_data_root = "/srv/hpc-link/data"
        mock_get_request_user.return_value = AuthenticatedUser(
            user_id=202,
            username="Alice Example",
            is_admin=False,
            invited=True,
            is_active=True,
            allowed_partitions=[],
            allowed_gpu_types=[],
            max_duration_minutes=30,
            max_gpu_count=1,
        )

        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)
        dir_attrs = MagicMock()
        dir_attrs.permissions = 0o40755
        mock_sftp.stat.return_value = dir_attrs
        mock_sftp.readdir.return_value = []

        response = self.client.get("/api/files/list?path=")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "/srv/hpc-link/data/users/alice_example")

    @patch('app.routers.files.get_request_user')
    @patch('app.routers.files.ssh_manager')
    def test_non_admin_realpath_escape_is_rejected(self, mock_ssh_manager, mock_get_request_user):
        mock_get_request_user.return_value = AuthenticatedUser(
            user_id=203,
            username="alice",
            is_admin=False,
            invited=True,
            is_active=True,
            allowed_partitions=[],
            allowed_gpu_types=[],
            max_duration_minutes=30,
            max_gpu_count=1,
        )

        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)
        mock_sftp.realpath.return_value = "/srv/hpc-link/data/users/bob"

        response = self.client.get("/api/files/list?path=/srv/hpc-link/data/users/alice/link")

        self.assertEqual(response.status_code, 403)

    @patch('app.routers.files.ssh_manager')
    def test_mkdir(self, mock_ssh_manager):
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        mock_sftp.exists.return_value = False

        response = self.client.post("/api/files/mkdir", json={"path": "/srv/hpc-link/data/new_dir"})

        self.assertEqual(response.status_code, 200)
        mock_sftp.makedirs.assert_called_with("/srv/hpc-link/data/new_dir")

    @patch('app.routers.files.ssh_manager')
    def test_delete_file(self, mock_ssh_manager):
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        mock_sftp.exists.return_value = True
        mock_sftp.isdir.return_value = False

        response = self.client.delete("/api/files?path=/srv/hpc-link/data/file_to_delete")

        self.assertEqual(response.status_code, 200)
        mock_sftp.remove.assert_called_with("/srv/hpc-link/data/file_to_delete")

    @patch('app.routers.files.ssh_manager')
    def test_delete_directory(self, mock_ssh_manager):
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        mock_sftp.exists.return_value = True
        mock_sftp.isdir.return_value = True

        response = self.client.delete("/api/files?path=/srv/hpc-link/data/dir_to_delete")

        self.assertEqual(response.status_code, 200)
        mock_sftp.rmtree.assert_called_with("/srv/hpc-link/data/dir_to_delete")

    @patch('app.routers.files.ssh_manager')
    def test_get_stat(self, mock_ssh_manager):
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        attrs = MagicMock()
        attrs.size = 123
        attrs.mtime = 456
        attrs.permissions = 0o100644
        mock_sftp.stat.return_value = attrs

        response = self.client.get("/api/files/stat?path=/srv/hpc-link/data/some_file")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['size'], 123)
        self.assertEqual(data['name'], 'some_file')

    @patch('app.routers.files.ssh_manager')
    @patch('app.security.get_settings')
    @patch('app.routers.files.get_settings')
    def test_list_directory_default_path(self, mock_files_settings, mock_security_settings, mock_ssh_manager):
        # Create a shared settings mock
        settings_obj = MagicMock()
        settings_obj.hpc_data_root = "/default/root"
        settings_obj.api_key = None # Ensure no auth issues if checked

        mock_files_settings.return_value = settings_obj
        mock_security_settings.return_value = settings_obj

        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # Mock stat valid dir
        dir_attrs = MagicMock()
        dir_attrs.permissions = 0o40755
        mock_sftp.stat.return_value = dir_attrs

        mock_sftp.readdir.return_value = []

        # Empty path
        response = self.client.get("/api/files/list?path=")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "/default/root")

    @patch('app.routers.files.ssh_manager')
    @patch('app.config.get_settings')
    def test_list_directory_not_a_directory(self, mock_settings, mock_ssh_manager):
        mock_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # Mock stat file (not dir)
        file_attrs = MagicMock()
        file_attrs.permissions = 0o100644 # Regular file
        mock_sftp.stat.return_value = file_attrs

        # Use a valid path inside root
        response = self.client.get("/api/files/list?path=/srv/hpc-link/data/file.txt")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a directory", response.json()["detail"])

    @patch('app.routers.files.ssh_manager')
    def test_upload_invalid_session(self, mock_ssh_manager):
        response = self.client.put(
            "/api/files/upload/invalid-uuid",
            content=b"data",
            headers={"Content-Type": "application/octet-stream"}
        )
        self.assertEqual(response.status_code, 404)

    @patch('app.routers.files.get_settings')
    @patch('app.routers.files.ssh_manager')
    def test_upload_session_quota(self, mock_ssh_manager, mock_get_settings):
        mock_get_settings.return_value.upload_session_ttl_seconds = 1800
        mock_get_settings.return_value.upload_max_active_sessions = 1
        mock_get_settings.return_value.upload_max_active_sessions_per_user = 1
        mock_get_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)
        mock_file_ctx = AsyncMock()
        mock_file_ctx.__aenter__.return_value = AsyncMock()
        mock_sftp.open = MagicMock(return_value=mock_file_ctx)

        first = self.client.post("/api/files/upload/init", json={"path": "/srv/hpc-link/data/one.bin"})
        self.assertEqual(first.status_code, 200)

        second = self.client.post("/api/files/upload/init", json={"path": "/srv/hpc-link/data/two.bin"})
        self.assertEqual(second.status_code, 429)

    @patch('app.routers.files.get_settings')
    @patch('app.routers.files.ssh_manager')
    def test_upload_chunk_size_limit(self, mock_ssh_manager, mock_get_settings):
        mock_get_settings.return_value.upload_session_ttl_seconds = 1800
        mock_get_settings.return_value.upload_max_chunk_bytes = 4
        mock_get_settings.return_value.upload_max_file_bytes = 10
        mock_get_settings.return_value.hpc_data_root = "/srv/hpc-link/data"
        now = time.monotonic()
        upload_sessions["upload-id"] = {
            "path": "/srv/hpc-link/data/large.bin",
            "temp_path": "/srv/hpc-link/data/large.bin.part",
            "owner": "service-api-key",
            "bytes_written": 0,
            "created_at": now,
            "last_activity": now,
        }

        response = self.client.put(
            "/api/files/upload/upload-id",
            content=b"12345",
            headers={"Content-Type": "application/octet-stream"},
        )

        self.assertEqual(response.status_code, 413)
        mock_ssh_manager.open_sftp.assert_not_called()

    @patch('app.main.get_settings')
    @patch('app.routers.files.get_settings')
    @patch('app.routers.files.ssh_manager')
    def test_streaming_upload_body_size_limit(self, mock_ssh_manager, mock_router_settings, mock_main_settings):
        settings = MagicMock()
        settings.upload_session_ttl_seconds = 1800
        settings.upload_max_chunk_bytes = 4
        settings.upload_max_file_bytes = 10
        settings.upload_pi3_max_body_bytes = 30
        settings.upload_marker_max_body_bytes = 140
        settings.webhdp_component_test_max_body_bytes = 32
        settings.hpc_data_root = "/srv/hpc-link/data"
        mock_main_settings.return_value = settings
        mock_router_settings.return_value = settings
        now = time.monotonic()
        upload_sessions["upload-id"] = {
            "path": "/srv/hpc-link/data/large.bin",
            "temp_path": "/srv/hpc-link/data/large.bin.part",
            "owner": "service-api-key",
            "bytes_written": 0,
            "created_at": now,
            "last_activity": now,
        }

        def body_chunks():
            yield b"12"
            yield b"345"

        response = self.client.put(
            "/api/files/upload/upload-id",
            content=body_chunks(),
            headers={"Content-Type": "application/octet-stream"},
        )

        self.assertEqual(response.status_code, 413)
        self.assertIn("Request body too large", response.json()["detail"])
        mock_ssh_manager.open_sftp.assert_not_called()

    @patch('app.routers.files.get_settings')
    @patch('app.routers.files.ssh_manager')
    def test_upload_total_size_limit(self, mock_ssh_manager, mock_get_settings):
        mock_get_settings.return_value.upload_session_ttl_seconds = 1800
        mock_get_settings.return_value.upload_max_chunk_bytes = 4
        mock_get_settings.return_value.upload_max_file_bytes = 6
        mock_get_settings.return_value.hpc_data_root = "/srv/hpc-link/data"
        now = time.monotonic()
        upload_sessions["upload-id"] = {
            "path": "/srv/hpc-link/data/large.bin",
            "temp_path": "/srv/hpc-link/data/large.bin.part",
            "owner": "service-api-key",
            "bytes_written": 4,
            "created_at": now,
            "last_activity": now,
        }

        response = self.client.put(
            "/api/files/upload/upload-id",
            content=b"123",
            headers={"Content-Type": "application/octet-stream"},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(upload_sessions["upload-id"]["bytes_written"], 4)
        mock_ssh_manager.open_sftp.assert_not_called()

    @patch('app.routers.files.get_settings')
    @patch('app.routers.files.ssh_manager')
    def test_finish_upload_size_limit_removes_temp_file(self, mock_ssh_manager, mock_get_settings):
        mock_get_settings.return_value.upload_session_ttl_seconds = 1800
        mock_get_settings.return_value.upload_max_file_bytes = 4
        mock_get_settings.return_value.hpc_data_root = "/srv/hpc-link/data"
        now = time.monotonic()
        upload_sessions["upload-id"] = {
            "path": "/srv/hpc-link/data/large.bin",
            "temp_path": "/srv/hpc-link/data/large.bin.part",
            "owner": "service-api-key",
            "bytes_written": 5,
            "created_at": now,
            "last_activity": now,
        }
        mock_sftp = AsyncMock()
        mock_sftp.stat.return_value.size = 5
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        response = self.client.post("/api/files/upload/upload-id/finish")

        self.assertEqual(response.status_code, 413)
        mock_sftp.remove.assert_called_with("/srv/hpc-link/data/large.bin.part")
        self.assertNotIn("upload-id", upload_sessions)

if __name__ == '__main__':
    unittest.main()
