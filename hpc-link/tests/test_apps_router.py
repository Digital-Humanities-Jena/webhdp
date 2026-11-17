import unittest
import asyncio
import base64
import json
import stat
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.auth_store import AuthenticatedUser
from app.main import app
from app.schemas.apps import (
    WebHdpCloudStageFile,
    WebHdpCloudStageRequest,
    WebHdpComponentInstallRequest,
    WebHdpComponentInstallValidateRequest,
    WebHdpComponentRunRequest,
    WebHdpZenodoDraftFile,
    WebHdpZenodoDraftUploadRequest,
)
from app.security import get_api_key
from app.services.apps_gateway import HpcApplicationGatewayService, _WebHdpSession


class TestAppsRouter(unittest.TestCase):
    def setUp(self):
        async def test_auth(request: Request):
            request.state.current_user = self._admin_user("tester")
            return "test-key"

        app.dependency_overrides[get_api_key] = test_auth
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = {}

    def _admin_user(self, username: str = "admin") -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=1,
            username=username,
            is_admin=True,
            invited=True,
            is_active=True,
            allowed_partitions=[],
            allowed_gpu_types=[],
            max_duration_minutes=240,
            max_gpu_count=8,
        )

    @patch("app.routers.apps.hpc_application_service")
    def test_list_apps(self, mock_service):
        mock_service.list_applications = AsyncMock(
            return_value=[
                {
                    "app_id": "vllm",
                    "name": "vLLM Chat Runtime",
                    "description": "desc",
                }
            ]
        )
        response = self.client.get("/api/apps")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["app_id"], "vllm")

    @patch("app.routers.apps.hpc_application_service")
    def test_create_vllm_session(self, mock_service):
        now = datetime.now(timezone.utc)
        mock_service.create_vllm_session = AsyncMock(
            return_value={
                "session_id": "abc123",
                "app_id": "vllm",
                "model_id": "tinyllama-1.1b",
                "model_label": "TinyLlama 1.1B Chat",
                "job_id": "12345",
                "remote_session_dir": "/srv/hpc-link/apps/vllm/sessions/abc123",
                "status": "queued",
                "created_at": now,
                "expires_at": now + timedelta(minutes=30),
            }
        )

        response = self.client.post(
            "/api/apps/vllm/sessions",
            json={"model_id": "tinyllama-1.1b", "duration_minutes": 30, "gpu_count": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "abc123")

    @patch("app.routers.apps.hpc_application_service")
    def test_chat_vllm_session(self, mock_service):
        mock_service.chat_vllm_session = AsyncMock(
            return_value={
                "session_id": "abc123",
                "model_id": "tinyllama-1.1b",
                "reply": "Hello from model",
                "usage_prompt_tokens": 12,
                "usage_completion_tokens": 8,
            }
        )

        response = self.client.post(
            "/api/apps/vllm/sessions/abc123/chat",
            json={"message": "Hello", "temperature": 0.2, "max_tokens": 128},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Hello from model")

    @patch("app.routers.apps.hpc_application_service")
    def test_stop_vllm_session(self, mock_service):
        mock_service.stop_vllm_session = AsyncMock(
            return_value={
                "session_id": "abc123",
                "job_id": "12345",
                "cancelled": True,
                "message": "Session cancelled",
            }
        )
        response = self.client.delete("/api/apps/vllm/sessions/abc123")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cancelled"])

    @patch("app.routers.apps.hpc_application_service")
    def test_create_pi3_session(self, mock_service):
        now = datetime.now(timezone.utc)
        mock_service.create_pi3_session = AsyncMock(
            return_value={
                "session_id": "pi3001",
                "app_id": "pi3",
                "job_id": "55555",
                "partition": "partition-b",
                "gpu_count": 1,
                "remote_session_dir": "/srv/hpc-link/apps/pi3/sessions/pi3001",
                "input_dir": "/srv/hpc-link/apps/pi3/sessions/pi3001/input_images",
                "output_dir": "/srv/hpc-link/apps/pi3/sessions/pi3001/outputs",
                "status": "queued",
                "created_at": now,
                "expires_at": now + timedelta(minutes=30),
            }
        )
        response = self.client.post(
            "/api/apps/pi3/sessions",
            json={"partition": "partition-b", "duration_minutes": 30, "gpu_count": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["app_id"], "pi3")

    @patch("app.routers.apps.hpc_application_service")
    def test_upload_pi3_image(self, mock_service):
        payload = base64.b64encode(b"image-bytes").decode("ascii")
        mock_service.upload_pi3_image = AsyncMock(
            return_value={
                "session_id": "pi3001",
                "filename": "image_0.png",
                "remote_path": "/srv/hpc-link/apps/pi3/sessions/pi3001/input_images/image_0.png",
                "size_bytes": 11,
            }
        )
        response = self.client.post(
            "/api/apps/pi3/sessions/pi3001/images",
            json={"filename": "image_0.png", "content_base64": payload},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["filename"], "image_0.png")

    @patch("app.routers.apps.hpc_application_service")
    def test_process_pi3_session(self, mock_service):
        mock_service.process_pi3_session = AsyncMock(
            return_value={
                "session_id": "pi3001",
                "job_id": "55555",
                "output_name": "result.ply",
                "artifact_path": "/srv/hpc-link/apps/pi3/sessions/pi3001/outputs/result.ply",
                "size_bytes": 123456,
                "command_stdout_tail": "done",
                "command_stderr_tail": "",
            }
        )
        response = self.client.post(
            "/api/apps/pi3/sessions/pi3001/process",
            json={"output_name": "result.ply", "interval": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["output_name"], "result.ply")

    @patch("app.routers.apps.hpc_application_service")
    def test_list_pi3_artifacts(self, mock_service):
        mock_service.list_pi3_artifacts = AsyncMock(
            return_value={
                "session_id": "pi3001",
                "artifacts": [
                    {
                        "name": "result.ply",
                        "path": "/srv/hpc-link/apps/pi3/sessions/pi3001/outputs/result.ply",
                        "size_bytes": 123456,
                        "mtime_epoch": 1739291000,
                    }
                ],
            }
        )
        response = self.client.get("/api/apps/pi3/sessions/pi3001/artifacts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["artifacts"]), 1)

    @patch("app.routers.apps.hpc_application_service")
    def test_download_pi3_artifact(self, mock_service):
        mock_service.download_pi3_artifact = AsyncMock(
            return_value={
                "session_id": "pi3001",
                "artifact_name": "result.ply",
                "content_base64": base64.b64encode(b"ply").decode("ascii"),
                "size_bytes": 3,
                "media_type": "application/octet-stream",
            }
        )
        response = self.client.get("/api/apps/pi3/sessions/pi3001/artifacts/result.ply")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["artifact_name"], "result.ply")

    @patch("app.routers.apps.hpc_application_service")
    def test_stop_pi3_session(self, mock_service):
        mock_service.stop_pi3_session = AsyncMock(
            return_value={
                "session_id": "pi3001",
                "job_id": "55555",
                "cancelled": True,
                "message": "Pi3 session cancelled",
            }
        )
        response = self.client.delete("/api/apps/pi3/sessions/pi3001")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cancelled"])

    @patch("app.routers.apps.hpc_application_service")
    def test_create_marker_session(self, mock_service):
        now = datetime.now(timezone.utc)
        mock_service.create_marker_session = AsyncMock(
            return_value={
                "session_id": "marker001",
                "app_id": "marker",
                "job_id": "77777",
                "partition": "partition-b",
                "gpu_count": 1,
                "remote_session_dir": "/srv/hpc-link/apps/marker/sessions/marker001",
                "input_dir": "/srv/hpc-link/apps/marker/sessions/marker001/input_documents",
                "output_dir": "/srv/hpc-link/apps/marker/sessions/marker001/outputs",
                "status": "queued",
                "created_at": now,
                "expires_at": now + timedelta(minutes=30),
            }
        )
        response = self.client.post(
            "/api/apps/marker/sessions",
            json={"partition": "partition-b", "duration_minutes": 30, "gpu_count": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["app_id"], "marker")

    @patch("app.routers.apps.hpc_application_service")
    def test_upload_marker_document(self, mock_service):
        payload = base64.b64encode(b"%PDF-1.7").decode("ascii")
        mock_service.upload_marker_document = AsyncMock(
            return_value={
                "session_id": "marker001",
                "filename": "sample.pdf",
                "remote_path": "/srv/hpc-link/apps/marker/sessions/marker001/input_documents/sample.pdf",
                "size_bytes": 8,
            }
        )
        response = self.client.post(
            "/api/apps/marker/sessions/marker001/documents",
            json={"filename": "sample.pdf", "content_base64": payload},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["filename"], "sample.pdf")

    @patch("app.routers.apps.hpc_application_service")
    def test_convert_marker_document(self, mock_service):
        mock_service.convert_marker_document = AsyncMock(
            return_value={
                "session_id": "marker001",
                "job_id": "77777",
                "input_filename": "sample.pdf",
                "output_format": "markdown",
                "artifact_count": 1,
                "artifacts": [
                    {
                        "name": "sample.md",
                        "path": "/srv/hpc-link/apps/marker/sessions/marker001/outputs/sample.md",
                        "size_bytes": 4567,
                        "mtime_epoch": 1739291000,
                    }
                ],
                "command_stdout_tail": "done",
                "command_stderr_tail": "",
            }
        )
        response = self.client.post(
            "/api/apps/marker/sessions/marker001/convert",
            json={"input_filename": "sample.pdf", "output_format": "markdown"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["artifact_count"], 1)

    @patch("app.routers.apps.hpc_application_service")
    def test_list_marker_artifacts(self, mock_service):
        mock_service.list_marker_artifacts = AsyncMock(
            return_value={
                "session_id": "marker001",
                "artifacts": [
                    {
                        "name": "sample.md",
                        "path": "/srv/hpc-link/apps/marker/sessions/marker001/outputs/sample.md",
                        "size_bytes": 4567,
                        "mtime_epoch": 1739291000,
                    }
                ],
            }
        )
        response = self.client.get("/api/apps/marker/sessions/marker001/artifacts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["artifacts"]), 1)

    @patch("app.routers.apps.hpc_application_service")
    def test_download_marker_artifact(self, mock_service):
        mock_service.download_marker_artifact = AsyncMock(
            return_value={
                "session_id": "marker001",
                "artifact_name": "sample.md",
                "content_base64": base64.b64encode(b"# title").decode("ascii"),
                "size_bytes": 7,
                "media_type": "text/markdown",
            }
        )
        response = self.client.get("/api/apps/marker/sessions/marker001/artifacts/sample.md")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["artifact_name"], "sample.md")

    @patch("app.routers.apps.hpc_application_service")
    def test_stop_marker_session(self, mock_service):
        mock_service.stop_marker_session = AsyncMock(
            return_value={
                "session_id": "marker001",
                "job_id": "77777",
                "cancelled": True,
                "message": "Marker session cancelled",
            }
        )
        response = self.client.delete("/api/apps/marker/sessions/marker001")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cancelled"])

    @patch("app.routers.apps.hpc_application_service")
    def test_webhdp_zenodo_draft_upload_route(self, mock_service):
        mock_service.upload_webhdp_zenodo_draft = AsyncMock(
            return_value={
                "session_id": "webhdp001",
                "success": True,
                "environment": "sandbox",
                "deposition_id": "9001",
                "bucket_url": "https://sandbox.zenodo.org/api/files/bucket",
                "uploaded_files": [
                    {
                        "name": "render.png",
                        "remote_path": "/srv/hpc-link/apps/webhdp/sessions/webhdp001/outputs/render.png",
                        "size_bytes": 1024,
                        "response": {"key": "render.png"},
                    }
                ],
                "publish_requested": False,
                "error": None,
            }
        )
        response = self.client.post(
            "/api/apps/webhdp/sessions/webhdp001/zenodo/upload-draft",
            json={
                "environment": "sandbox",
                "access_token": "sandbox-token",
                "files": [
                    {
                        "remote_path": "/srv/hpc-link/apps/webhdp/sessions/webhdp001/outputs/render.png",
                        "name": "render.png",
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertFalse(response.json()["publish_requested"])

    def test_webhdp_cpu_only_batch_script_omits_gres(self):
        service = HpcApplicationGatewayService()
        now = datetime.now(timezone.utc)
        session = _WebHdpSession(
            session_id="webhdp001",
            partition="partition-a",
            gpu_type=None,
            gpu_count=0,
            duration_minutes=30,
            time_limit="00:30:00",
            job_id="",
            remote_session_dir="/work/webhdp/session",
            remote_input_dir="/work/webhdp/session/inputs",
            remote_output_dir="/work/webhdp/session/outputs",
            cuda_module=None,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            owner_username="tester",
        )

        script = service._render_webhdp_hold_batch_script(session)

        self.assertIn("#SBATCH --partition=partition-a", script)
        self.assertNotIn("#SBATCH --gres=", script)

    def test_webhdp_gpu_batch_script_includes_typed_gres(self):
        service = HpcApplicationGatewayService()
        now = datetime.now(timezone.utc)
        session = _WebHdpSession(
            session_id="webhdp002",
            partition="partition-b",
            gpu_type="a100",
            gpu_count=2,
            duration_minutes=30,
            time_limit="00:30:00",
            job_id="",
            remote_session_dir="/work/webhdp/session",
            remote_input_dir="/work/webhdp/session/inputs",
            remote_output_dir="/work/webhdp/session/outputs",
            cuda_module=None,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            owner_username="tester",
        )

        script = service._render_webhdp_hold_batch_script(session)

        self.assertIn("#SBATCH --gres=gpu:a100:2", script)

    def test_webhdp_cloud_stage_url_validation(self):
        service = HpcApplicationGatewayService()

        with patch.object(service, "_reject_private_resolved_addresses") as mock_resolve:
            self.assertEqual(
                service._validate_stage_url("https://dl.dropboxusercontent.com/file.bin"),
                "https://dl.dropboxusercontent.com/file.bin",
            )
            mock_resolve.assert_called_once_with("dl.dropboxusercontent.com", 443)

        for url in (
            "http://dl.dropboxusercontent.com/file.bin",
            "https://example.com/file.bin",
            "https://webhdp.example.com.evil.test/file.bin",
        ):
            with self.subTest(url=url):
                with self.assertRaises(HTTPException):
                    service._validate_stage_url(url)

    def test_webhdp_cloud_stage_url_rejects_private_resolved_addresses(self):
        service = HpcApplicationGatewayService()

        with patch.dict("os.environ", {"HPC_LINK_ALLOWED_STAGE_HOSTS": "127.0.0.1"}):
            with self.assertRaises(HTTPException) as context:
                service._validate_stage_url("https://127.0.0.1/file.bin")

        self.assertIn("non-public network", context.exception.detail)

    def test_webhdp_sif_download_url_uses_stage_url_guards(self):
        service = HpcApplicationGatewayService()

        with self.assertRaises(HTTPException):
            service._validate_sif_download_url("https://example.com/component.sif")

        with patch.object(service, "_reject_private_resolved_addresses") as mock_resolve:
            self.assertEqual(
                service._validate_sif_download_url("https://dl.dropboxusercontent.com/component.sif"),
                "https://dl.dropboxusercontent.com/component.sif",
            )
            mock_resolve.assert_called_once_with("dl.dropboxusercontent.com", 443)

    def test_webhdp_sif_download_rejects_private_url_credentials(self):
        service = HpcApplicationGatewayService()
        with patch.object(service, "_reject_private_resolved_addresses") as resolve:
            for url in (
                "https://zenodo.org/files/component.sif?download=1&token=private-value",
                "https://user:private-value@zenodo.org/files/component.sif",
                "https://zenodo.org/files/component.sif#private-value",
                "https://zenodo.org/files/component.sif;token=private-value",
                "https://dl.dropboxusercontent.com/files/component.sif?download=1",
            ):
                with self.subTest(url=url), self.assertRaises(HTTPException) as exc:
                    service._validate_sif_download_url(url)
                self.assertNotIn("private-value", exc.exception.detail)
            resolve.assert_not_called()
            url = "https://zenodo.org/files/component.sif?download=1"
            self.assertEqual(service._validate_sif_download_url(url), url)
            resolve.assert_called_once_with("zenodo.org", 443)

    def test_webhdp_cloud_stage_rejects_too_many_files(self):
        service = HpcApplicationGatewayService()
        service._settings.webhdp_cloud_stage_max_files = 1
        now = datetime.now(timezone.utc)
        service._webhdp_sessions["webhdp-stage"] = _WebHdpSession(
            session_id="webhdp-stage",
            partition="partition-b",
            gpu_type=None,
            gpu_count=0,
            duration_minutes=30,
            time_limit="00:30:00",
            job_id="123",
            remote_session_dir="/work/apps/webhdp/sessions/webhdp-stage",
            remote_input_dir="/work/apps/webhdp/sessions/webhdp-stage/inputs",
            remote_output_dir="/work/apps/webhdp/sessions/webhdp-stage/outputs",
            cuda_module=None,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            owner_username="tester",
        )
        request = WebHdpCloudStageRequest(
            files=[
                WebHdpCloudStageFile(url="https://dl.dropboxusercontent.com/a", name="a.bin"),
                WebHdpCloudStageFile(url="https://dl.dropboxusercontent.com/b", name="b.bin"),
            ]
        )

        with self.assertRaises(HTTPException) as context:
            asyncio.run(service.stage_webhdp_cloud_files("webhdp-stage", request, self._admin_user("tester")))

        self.assertEqual(context.exception.status_code, 413)

    @patch("app.services.apps_gateway.ssh_manager")
    def test_webhdp_cloud_stage_removes_failed_download_target(self, mock_ssh_manager):
        service = HpcApplicationGatewayService()
        now = datetime.now(timezone.utc)
        service._webhdp_sessions["webhdp-stage"] = _WebHdpSession(
            session_id="webhdp-stage",
            partition="partition-b",
            gpu_type=None,
            gpu_count=0,
            duration_minutes=30,
            time_limit="00:30:00",
            job_id="123",
            remote_session_dir="/work/apps/webhdp/sessions/webhdp-stage",
            remote_input_dir="/work/apps/webhdp/sessions/webhdp-stage/inputs",
            remote_output_dir="/work/apps/webhdp/sessions/webhdp-stage/outputs",
            cuda_module=None,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            owner_username="tester",
        )
        sftp = MagicMock()
        sftp.lstat = AsyncMock(return_value=SimpleNamespace(permissions=stat.S_IFDIR))
        sftp.remove = AsyncMock()
        mock_ssh_manager.open_sftp = AsyncMock(return_value=sftp)
        sftp.__aenter__.return_value = sftp
        mock_ssh_manager.run_command = AsyncMock(return_value=("", "sensitive upstream diagnostic", 22))
        request = WebHdpCloudStageRequest(
            files=[WebHdpCloudStageFile(url="https://dl.dropboxusercontent.com/a", name="a.bin")]
        )

        with patch.object(service, "_reject_private_resolved_addresses", return_value=['8.8.8.8']):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(service.stage_webhdp_cloud_files("webhdp-stage", request, self._admin_user("tester")))

        self.assertEqual(context.exception.status_code, 502)
        self.assertTrue(sftp.remove.call_args.args[0].startswith("/work/apps/webhdp/sessions/webhdp-stage/inputs/a.bin.part-"))
        self.assertNotIn('sensitive upstream diagnostic', context.exception.detail)

    @patch('app.services.apps_gateway.ssh_manager')
    def test_cloud_download_revalidates_pins_and_hides_redirect_urls(self, ssh):
        service = HpcApplicationGatewayService()
        ssh.run_command = AsyncMock(side_effect=[
            ('302\nhttps://dl.dropboxusercontent.com/final?private=value\n', '', 0), ('200\n\n', '', 0),
        ])
        with patch.object(service, '_reject_private_resolved_addresses', side_effect=[['8.8.8.8'], ['8.8.4.4']]):
            asyncio.run(service._fetch_webhdp_cloud_file('https://dl.dropboxusercontent.com/start?private=value', '/work/output', 1000))
        for call, address in zip(ssh.run_command.call_args_list, ['8.8.8.8', '8.8.4.4'], strict=True):
            self.assertIn('--resolve dl.dropboxusercontent.com:443:' + address, call.args[0])
            self.assertNotIn('private=value', call.args[0])
            self.assertIn('private=value', call.kwargs['stdin'])
            self.assertNotIn('--location', call.args[0])

        ssh.run_command = AsyncMock(return_value=('302\nhttps://127.0.0.1/private\n', '', 0))
        with patch.object(service, '_reject_private_resolved_addresses', return_value=['8.8.8.8']):
            with self.assertRaises(HTTPException):
                asyncio.run(service._fetch_webhdp_cloud_file('https://dl.dropboxusercontent.com/start', '/work/output', 1000))
        self.assertEqual(ssh.run_command.await_count, 1)

    def test_staging_rejects_symlink_parent(self):
        service = HpcApplicationGatewayService()
        session = SimpleNamespace(remote_input_dir='/work/inputs')
        sftp = SimpleNamespace(lstat=AsyncMock(side_effect=[SimpleNamespace(permissions=stat.S_IFDIR),
                                                            SimpleNamespace(permissions=stat.S_IFLNK)]))
        with self.assertRaises(HTTPException) as context:
            asyncio.run(service._prepare_staged_input_parent(sftp, session, 'unsafe/file'))
        self.assertEqual(context.exception.status_code, 400)

    @patch("app.routers.apps.hpc_application_service")
    def test_run_webhdp_component_rejects_client_executable_profile(self, mock_service):
        mock_service.run_webhdp_component = AsyncMock()

        response = self.client.post(
            "/api/apps/webhdp/sessions/webhdp001/components/run",
            json={
                "component_key": "gltf_validator",
                "profile": {
                    "image": "/work/evil.sif",
                    "entrypoint": ["/bin/sh"],
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        mock_service.run_webhdp_component.assert_not_called()

    @patch("app.services.apps_gateway.ssh_manager")
    def test_run_webhdp_component_loads_installed_registry_profile(self, mock_ssh_manager):
        service = HpcApplicationGatewayService()
        now = datetime.now(timezone.utc)
        service._webhdp_sessions["webhdp-run"] = _WebHdpSession(
            session_id="webhdp-run",
            partition="partition-b",
            gpu_type=None,
            gpu_count=0,
            duration_minutes=30,
            time_limit="00:30:00",
            job_id="123",
            remote_session_dir="/work/apps/webhdp/sessions/webhdp-run",
            remote_input_dir="/work/apps/webhdp/sessions/webhdp-run/inputs",
            remote_output_dir="/work/apps/webhdp/sessions/webhdp-run/outputs",
            cuda_module=None,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            owner_username="tester",
        )
        registry = {
            "sif_remote_path": "/work/apps/webhdp/components/gltf_validator/1.0.0/component.sif",
            "manifest_path": "/work/apps/webhdp/components/gltf_validator/1.0.0/component.yaml",
        }
        manifest = {
            "execution": {
                "profiles": [
                    {
                        "handler": "generic_singularity_component",
                        "entrypoint": ["python", "/app/validator.py"],
                    }
                ]
            }
        }
        mock_ssh_manager.run_command = AsyncMock(
            side_effect=[
                ("RUNNING|None", "", 0),
                (str(now.timestamp()), "", 0),
                (__import__("json").dumps(registry), "", 0),
                (__import__("json").dumps(manifest), "", 0),
                ('{"success": true}', "", 0),
            ]
        )
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)
        mock_file = AsyncMock()
        mock_file_ctx = AsyncMock()
        mock_file_ctx.__aenter__.return_value = mock_file
        mock_sftp.open = MagicMock(return_value=mock_file_ctx)

        result = asyncio.run(
            service.run_webhdp_component(
                "webhdp-run",
                WebHdpComponentRunRequest(component_key="gltf_validator", component_version="1.0.0"),
                self._admin_user("tester"),
            )
        )

        self.assertTrue(result["success"])
        written_payload = __import__("json").loads(mock_file.write.call_args.args[0])
        self.assertEqual(
            written_payload["profile"]["image"],
            "/work/apps/webhdp/components/gltf_validator/1.0.0/component.sif",
        )

    @patch("app.services.apps_gateway.ssh_manager")
    def test_install_never_overwrites_an_existing_version_directory(self, mock_ssh_manager):
        service = HpcApplicationGatewayService()
        service.validate_webhdp_component_install = AsyncMock(return_value={"success": True})
        mock_ssh_manager.run_command = AsyncMock(return_value=("", "File exists", 1))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(service.install_webhdp_component(WebHdpComponentInstallRequest(component_key="validator", version="1.0.0", sif_source="/work/source.sif", source_type="remote_path", manifest_hash="hash"), self._admin_user()))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(mock_ssh_manager.run_command.call_count, 1)
        self.assertIn("mkdir -m 700", mock_ssh_manager.run_command.call_args.args[0])
        mock_ssh_manager.open_sftp.assert_not_called()

    @patch("app.services.apps_gateway.ssh_manager")
    def test_validate_webhdp_component_install_verifies_remote_sif_checksum(self, mock_ssh_manager):
        service = HpcApplicationGatewayService()
        checksum = "a" * 64
        mock_ssh_manager.run_command = AsyncMock(
            side_effect=[
                ("/usr/bin/singularity\n", "", 0),
                (f"42\n{checksum}\n", "", 0),
            ]
        )

        result = asyncio.run(
            service.validate_webhdp_component_install(
                WebHdpComponentInstallValidateRequest(
                    component_key="gltf_validator",
                    version="1.0.0",
                    sif_source="/work/components/gltf_validator.sif",
                    source_type="remote_path",
                    sif_sha256=checksum,
                    manifest={"metadata": {"name": "gltf_validator"}},
                ),
                self._admin_user("tester"),
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["checks"]["sif"]["sha256"], checksum)
        self.assertTrue(result["checks"]["sif_checksum"]["success"])

    @patch("app.services.apps_gateway.ssh_manager")
    def test_install_webhdp_component_rejects_checksum_mismatch(self, mock_ssh_manager):
        service = HpcApplicationGatewayService()
        expected = "a" * 64
        actual = "b" * 64
        mock_ssh_manager.run_command = AsyncMock(
            side_effect=[
                ("/usr/bin/singularity\n", "", 0),
                (f"42\n{expected}\n", "", 0),
                ("", "", 0),
                ("", "", 0),
                (f"{actual}\n", "", 0),
                ("", "", 0),
            ]
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                service.install_webhdp_component(
                    WebHdpComponentInstallRequest(
                        component_key="gltf_validator",
                        version="1.0.0",
                        sif_source="/work/components/gltf_validator.sif",
                        source_type="remote_path",
                        sif_sha256=expected,
                        manifest_hash="hash",
                        manifest={"metadata": {"name": "gltf_validator"}},
                    ),
                    self._admin_user("tester"),
                )
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("SHA-256", ctx.exception.detail)

    @patch("app.services.apps_gateway.ssh_manager")
    def test_install_webhdp_component_writes_checksum_to_registry(self, mock_ssh_manager):
        service = HpcApplicationGatewayService()
        checksum = "a" * 64
        mock_ssh_manager.run_command = AsyncMock(
            side_effect=[
                ("/usr/bin/singularity\n", "", 0),
                (f"42\n{checksum}\n", "", 0),
                ("", "", 0),
                ("", "", 0),
                (f"{checksum}\n", "", 0),
                ("", "", 0),
            ]
        )
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)
        writes = []

        def open_context(_path, _mode):
            handle = AsyncMock()
            handle.write = AsyncMock(side_effect=lambda value: writes.append(value))
            ctx = AsyncMock()
            ctx.__aenter__.return_value = handle
            return ctx

        mock_sftp.open = MagicMock(side_effect=open_context)

        result = asyncio.run(
            service.install_webhdp_component(
                WebHdpComponentInstallRequest(
                    component_key="gltf_validator",
                    version="1.0.0",
                    sif_source="/work/components/gltf_validator.sif",
                    source_type="remote_path",
                    sif_sha256=checksum,
                    manifest_hash="hash",
                    manifest={"metadata": {"name": "gltf_validator"}},
                ),
                self._admin_user("tester"),
            )
        )

        self.assertTrue(result["success"])
        registry_payload = next(__import__("json").loads(value) for value in writes if "sif_sha256" in value)
        self.assertEqual(registry_payload["sif_sha256"], checksum)
        self.assertEqual(result["logs"]["sif_checksum"]["actual_sha256"], checksum)

    def test_webhdp_zenodo_upload_rejects_client_bucket_url(self):
        service = HpcApplicationGatewayService()
        now = datetime.now(timezone.utc)
        service._webhdp_sessions["webhdp-zenodo"] = _WebHdpSession(
            session_id="webhdp-zenodo",
            partition="partition-b",
            gpu_type=None,
            gpu_count=0,
            duration_minutes=30,
            time_limit="00:30:00",
            job_id="123",
            remote_session_dir="/work/apps/webhdp/sessions/webhdp-zenodo",
            remote_input_dir="/work/apps/webhdp/sessions/webhdp-zenodo/inputs",
            remote_output_dir="/work/apps/webhdp/sessions/webhdp-zenodo/outputs",
            cuda_module=None,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            owner_username="tester",
        )
        request = WebHdpZenodoDraftUploadRequest(
            access_token="token",
            bucket_url="https://attacker.example/upload",
            files=[
                WebHdpZenodoDraftFile(
                    remote_path="/work/apps/webhdp/sessions/webhdp-zenodo/outputs/render.png",
                    name="render.png",
                )
            ],
        )

        with self.assertRaises(HTTPException) as context:
            asyncio.run(service.upload_webhdp_zenodo_draft("webhdp-zenodo", request, self._admin_user("tester")))

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("bucket_url", context.exception.detail)

    @patch('app.services.apps_gateway.ssh_manager')
    def test_zenodo_draft_passes_credentials_only_on_stdin(self, ssh):
        service = HpcApplicationGatewayService()
        input_path = '/work/session/outputs/model.glb'
        token = 'unit-test-private-value'
        service._webhdp_sessions['demo'] = SimpleNamespace(owner_username='tester', remote_output_dir='/work/session/outputs')
        service.get_webhdp_session_status = AsyncMock(return_value=SimpleNamespace(scheduler_state='RUNNING'))
        service._ensure_webhdp_session_regular_file = AsyncMock(return_value=(input_path, 5))
        ssh.open_sftp = AsyncMock(return_value=MagicMock())
        service._run_in_webhdp_allocation = AsyncMock(return_value=('{"success":true,"deposition_id":"123"}', '', 0))
        result = asyncio.run(service.upload_webhdp_zenodo_draft('demo', WebHdpZenodoDraftUploadRequest(
            access_token=token, files=[WebHdpZenodoDraftFile(remote_path=input_path)],
        ), self._admin_user('tester')))
        call = service._run_in_webhdp_allocation.call_args
        self.assertTrue(result.success)
        self.assertNotIn(token, call.args[1])
        self.assertEqual(json.loads(call.kwargs['stdin'])['access_token'], token)
        self.assertNotIn(token, result.model_dump_json())
        ssh.run_command.assert_not_called()

    def test_invalid_gateway_requests_do_not_echo_credentials(self):
        fake_secret = 'unit-test-private-value'
        response = self.client.post('/api/apps/webhdp/sessions/example/zenodo/upload-draft',
                                    json=[{'access_token': fake_secret}])
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(fake_secret, response.text)
        self.assertNotIn('input', response.json()['detail'][0])

    def test_webhdp_zenodo_upload_rejects_symlink_file(self):
        service = HpcApplicationGatewayService()
        now = datetime.now(timezone.utc)
        session = _WebHdpSession(
            session_id="webhdp-zenodo",
            partition="partition-b",
            gpu_type=None,
            gpu_count=0,
            duration_minutes=30,
            time_limit="00:30:00",
            job_id="123",
            remote_session_dir="/work/apps/webhdp/sessions/webhdp-zenodo",
            remote_input_dir="/work/apps/webhdp/sessions/webhdp-zenodo/inputs",
            remote_output_dir="/work/apps/webhdp/sessions/webhdp-zenodo/outputs",
            cuda_module=None,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            owner_username="tester",
        )
        mock_sftp = AsyncMock()
        attrs = MagicMock()
        attrs.permissions = 0o120777
        attrs.size = 10
        mock_sftp.lstat.return_value = attrs

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                service._ensure_webhdp_session_regular_file(
                    mock_sftp,
                    session,
                    "/work/apps/webhdp/sessions/webhdp-zenodo/outputs/link.png",
                )
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("symbolic links", context.exception.detail)

    @patch("app.routers.apps.hpc_application_service")
    def test_validate_webhdp_component_install_route(self, mock_service):
        mock_service.validate_webhdp_component_install = AsyncMock(
            return_value={"success": True, "checks": {"singularity": {"success": True}}}
        )

        response = self.client.post(
            "/api/apps/webhdp/components/validate-install",
            json={
                "component_key": "gltf_validator",
                "version": "1.0.0",
                "sif_source": "/work/components/gltf_validator.sif",
                "source_type": "remote_path",
                "manifest": {"metadata": {"name": "gltf_validator"}},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    @patch("app.routers.apps.hpc_application_service")
    def test_install_webhdp_component_route(self, mock_service):
        mock_service.install_webhdp_component = AsyncMock(
            return_value={
                "success": True,
                "component_key": "gltf_validator",
                "version": "1.0.0",
                "remote_install_dir": "/work/apps/webhdp/components/gltf_validator/1.0.0",
                "sif_remote_path": "/work/apps/webhdp/components/gltf_validator/1.0.0/component.sif",
                "manifest_path": "/work/apps/webhdp/components/gltf_validator/1.0.0/component.yaml",
                "registry_path": "/work/apps/webhdp/components/gltf_validator/1.0.0/component.json",
            "sif_sha256": "a" * 64,
                "checks": {},
                "logs": {},
                "error": None,
            }
        )

        response = self.client.post(
            "/api/apps/webhdp/components/install",
            json={
                "component_key": "gltf_validator",
                "version": "1.0.0",
                "sif_source": "/work/components/gltf_validator.sif",
                "source_type": "remote_path",
                "manifest_hash": "hash",
                "manifest": {"metadata": {"name": "gltf_validator"}},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sif_remote_path"], "/work/apps/webhdp/components/gltf_validator/1.0.0/component.sif")

    @patch("app.routers.apps.get_request_user")
    @patch("app.routers.apps.hpc_application_service")
    def test_install_webhdp_component_route_forbidden_for_non_admin(self, mock_service, mock_get_request_user):
        mock_get_request_user.return_value = AuthenticatedUser(
            user_id=301,
            username="demo",
            is_admin=False,
            invited=True,
            is_active=True,
            allowed_partitions=[],
            allowed_gpu_types=[],
            max_duration_minutes=30,
            max_gpu_count=1,
        )
        mock_service.install_webhdp_component = AsyncMock()

        response = self.client.post(
            "/api/apps/webhdp/components/install",
            json={
                "component_key": "gltf_validator",
                "version": "1.0.0",
                "sif_source": "/work/components/gltf_validator.sif",
                "source_type": "remote_path",
                "manifest_hash": "hash",
                "manifest": {"metadata": {"name": "gltf_validator"}},
            },
        )

        self.assertEqual(response.status_code, 403)
        mock_service.install_webhdp_component.assert_not_called()


if __name__ == "__main__":
    unittest.main()
