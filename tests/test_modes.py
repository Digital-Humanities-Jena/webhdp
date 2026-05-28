import unittest
import os
import shutil
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

# Import modules to test
# We need to set up path or assume we run from root
import sys
sys.path.append(os.getcwd())

from services.project_service import ProjectService
from session_manager import SessionManager

class TestProjectServiceModes(unittest.TestCase):

    def setUp(self):
        self.api_client = MagicMock()
        self.api_url = "http://mock-api"

    def test_docker_mode_translation(self):
        """Test path translation when HOST_SHARED_PATH differs from SHARED_SESSION_PATH"""
        os.environ["SHARED_SESSION_PATH"] = "/shared/sessions"
        os.environ["HOST_SHARED_PATH"] = "/Users/test/hdp-shared/sessions"

        service = ProjectService(self.api_url, self.api_client)

        container_path = "/shared/sessions/session_123/file.obj"
        expected_host_path = "/Users/test/hdp-shared/sessions/session_123/file.obj"

        translated = service._translate_path(container_path)
        self.assertEqual(translated, expected_host_path)

    def test_local_mode_no_translation(self):
        """Test path translation when HOST_SHARED_PATH is not set (Local Mode)"""
        # Unset HOST_SHARED_PATH to simulate local default
        if "HOST_SHARED_PATH" in os.environ:
            del os.environ["HOST_SHARED_PATH"]
        os.environ["SHARED_SESSION_PATH"] = "/tmp/custom_sessions"

        service = ProjectService(self.api_url, self.api_client)

        local_path = "/tmp/custom_sessions/session_456/file.obj"
        # Expect identity transformation
        translated = service._translate_path(local_path)
        self.assertEqual(translated, local_path)

        # Verify init logic
        self.assertEqual(service.host_shared_path, service.container_shared_path)

    def test_create_and_scan_prefers_local_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads_dir = os.path.join(temp_dir, "uploads")
            outputs_dir = os.path.join(temp_dir, "outputs")
            hdpc_path = os.path.join(temp_dir, "session.hdpc")
            os.makedirs(uploads_dir, exist_ok=True)
            os.makedirs(outputs_dir, exist_ok=True)
            with open(os.path.join(uploads_dir, "model.glb"), "w", encoding="utf-8") as handle:
                handle.write("glb")

            service = ProjectService(self.api_url, self.api_client)
            result = service.create_and_scan(
                hdpc_path=hdpc_path,
                data_in_path=uploads_dir,
                data_out_path=outputs_dir,
                project_name="Local scan",
                scan_options={
                    "extensions": [".glb"],
                    "primarysourceext": ".glb",
                    "bundling": {"enabled": False},
                    "batchEntity": "root",
                    "obj_options": {"add_mtl": False, "add_textures": False, "archive_subdirectories": False},
                },
            )

            self.assertTrue(result["success"])
            self.assertTrue(os.path.exists(hdpc_path))
            self.api_client.request.assert_not_called()
            self.api_client.get.assert_not_called()

    def test_local_inspect_and_record_lookup_do_not_fallback_to_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads_dir = os.path.join(temp_dir, "uploads")
            outputs_dir = os.path.join(temp_dir, "outputs")
            hdpc_path = os.path.join(temp_dir, "session.hdpc")
            os.makedirs(uploads_dir, exist_ok=True)
            os.makedirs(outputs_dir, exist_ok=True)
            with open(os.path.join(uploads_dir, "model.glb"), "w", encoding="utf-8") as handle:
                handle.write("glb")

            service = ProjectService(self.api_url, self.api_client)
            service.create_and_scan(
                hdpc_path=hdpc_path,
                data_in_path=uploads_dir,
                data_out_path=outputs_dir,
                project_name="Local scan",
                scan_options={
                    "extensions": [".glb"],
                    "primarysourceext": ".glb",
                    "bundling": {"enabled": False},
                    "batchEntity": "root",
                    "obj_options": {"add_mtl": False, "add_textures": False, "archive_subdirectories": False},
                },
            )

            file_map = service.get_file_id_map(hdpc_path)
            file_id = file_map["model.glb"]
            created = service.create_record_with_metadata(
                file_id,
                {
                    "title": "Prepared model",
                    "description": "Model description",
                    "creators": [{"name": "Museum"}],
                },
                is_sandbox=True,
                hdpc_path=hdpc_path,
            )
            inspect_data = service.inspect(hdpc_path, show_files=False)
            matched_record_id = service.find_record_for_file(hdpc_path, file_id)

            self.assertTrue(created["success"])
            self.assertEqual(matched_record_id, str(created["local_record_db_id"]))
            self.assertEqual(inspect_data["project_statistics"]["record_count"], 1)
            self.assertEqual(inspect_data["zenodo_records"][0]["source_file_id"], int(file_id))
            self.api_client.request.assert_not_called()
            self.api_client.get.assert_not_called()

    def test_add_source_files_prefers_local_hdpc_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads_dir = os.path.join(temp_dir, "uploads")
            outputs_dir = os.path.join(temp_dir, "outputs")
            hdpc_path = os.path.join(temp_dir, "session.hdpc")
            os.makedirs(uploads_dir, exist_ok=True)
            os.makedirs(outputs_dir, exist_ok=True)
            with open(os.path.join(uploads_dir, "model.glb"), "w", encoding="utf-8") as handle:
                handle.write("glb")
            preview_path = os.path.join(outputs_dir, "preview.png")
            with open(preview_path, "w", encoding="utf-8") as handle:
                handle.write("png")

            service = ProjectService(self.api_url, self.api_client)
            service.create_and_scan(
                hdpc_path=hdpc_path,
                data_in_path=uploads_dir,
                data_out_path=outputs_dir,
                project_name="Local add files",
                scan_options={
                    "extensions": [".glb"],
                    "primarysourceext": ".glb",
                    "bundling": {"enabled": False},
                    "batchEntity": "root",
                    "obj_options": {"add_mtl": False, "add_textures": False, "archive_subdirectories": False},
                },
            )

            added = service.add_source_files(
                [preview_path],
                pipeline_name="render",
                step_name="preview_generation",
                hdpc_path=hdpc_path,
            )

            self.assertTrue(added["success"])
            conn = sqlite3.connect(hdpc_path)
            try:
                row = conn.execute(
                    "SELECT file_type, pipeline_source, step_source FROM source_files WHERE absolute_path = ?",
                    (preview_path,),
                ).fetchone()
            finally:
                conn.close()

            self.assertIsNotNone(row)
            self.assertEqual(row[0], "generated")
            self.assertEqual(row[1], "render")
            self.assertEqual(row[2], "preview_generation")
            self.api_client.request.assert_not_called()
            self.api_client.get.assert_not_called()

    def test_add_source_files_does_not_fallback_to_api_when_local_hdpc_is_active(self):
        service = ProjectService(self.api_url, self.api_client)
        with tempfile.TemporaryDirectory() as temp_dir:
            hdpc_path = os.path.join(temp_dir, "session.hdpc")
            with open(hdpc_path, "w", encoding="utf-8") as handle:
                handle.write("")

            with patch("services.project_service.add_local_source_files", side_effect=RuntimeError("local failure")):
                with self.assertRaises(RuntimeError):
                    service.add_source_files(
                        [os.path.join(temp_dir, "preview.png")],
                        pipeline_name="render",
                        step_name="preview_generation",
                        hdpc_path=hdpc_path,
                    )

        self.api_client.request.assert_not_called()
        self.api_client.get.assert_not_called()

    def test_create_zenodo_record_prefers_local_hdpc_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads_dir = os.path.join(temp_dir, "uploads")
            outputs_dir = os.path.join(temp_dir, "outputs")
            hdpc_path = os.path.join(temp_dir, "session.hdpc")
            os.makedirs(uploads_dir, exist_ok=True)
            os.makedirs(outputs_dir, exist_ok=True)
            with open(os.path.join(uploads_dir, "model.glb"), "w", encoding="utf-8") as handle:
                handle.write("glb")

            service = ProjectService(self.api_url, self.api_client)
            service.create_and_scan(
                hdpc_path=hdpc_path,
                data_in_path=uploads_dir,
                data_out_path=outputs_dir,
                project_name="Local zenodo draft",
                scan_options={
                    "extensions": [".glb"],
                    "primarysourceext": ".glb",
                    "bundling": {"enabled": False},
                    "batchEntity": "root",
                    "obj_options": {"add_mtl": False, "add_textures": False, "archive_subdirectories": False},
                },
            )
            file_id = service.get_file_id_map(hdpc_path)["model.glb"]

            with patch(
                "services.project_service.create_local_api_draft",
                return_value={"success": True, "local_record_db_id": 1, "zenodo_response": {"id": 9001}},
            ) as local_draft:
                created = service.create_zenodo_record(file_id, is_sandbox=True, hdpc_path=hdpc_path)

            self.assertTrue(created["success"])
            self.assertEqual(created["zenodo_response"]["id"], 9001)
            local_draft.assert_called_once()

            conn = sqlite3.connect(hdpc_path)
            try:
                row = conn.execute(
                    "SELECT source_file_id, record_status, record_title FROM zenodo_records WHERE record_id = 1",
                ).fetchone()
            finally:
                conn.close()

            self.assertIsNotNone(row)
            self.assertEqual(row[0], int(file_id))
            self.assertEqual(row[1], "prepared")
            self.assertEqual(row[2], "Record for model.glb")
            self.api_client.request.assert_not_called()
            self.api_client.get.assert_not_called()

    def test_missing_local_hdpc_path_fails_with_clear_error(self):
        service = ProjectService("", self.api_client)

        with self.assertRaises(FileNotFoundError) as ctx:
            service.inspect("/tmp/nonexistent-session.hdpc", show_files=False)

        self.assertIn("Local .hdpc project file not found", str(ctx.exception))

class TestSessionManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        os.environ["SHARED_SESSION_PATH"] = self.test_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_create_session_dirs(self):
        """Test that session directories are created in the configured path"""
        manager = SessionManager(session_timeout=60)
        hdpc, data_out, uploads, session_dir = manager.create_session_dirs()

        # Verify paths start with the configured SHARED_SESSION_PATH
        self.assertTrue(session_dir.startswith(self.test_dir))
        self.assertTrue(os.path.exists(session_dir))
        self.assertTrue(os.path.exists(data_out))
        self.assertTrue(os.path.exists(uploads))

if __name__ == '__main__':
    unittest.main()
