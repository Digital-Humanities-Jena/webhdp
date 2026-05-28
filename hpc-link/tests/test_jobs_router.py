import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request, WebSocket
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.job import JobConfig
from app.security import get_api_key, get_ws_api_key
from app.auth_store import AuthenticatedUser

class TestJobsRouter(unittest.TestCase):
    def setUp(self):
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

        app.dependency_overrides[get_api_key] = test_auth
        app.dependency_overrides[get_ws_api_key] = test_ws_auth
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = {}

    @patch('app.routers.jobs.ssh_manager')
    def test_submit_job(self, mock_ssh_manager):
        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # Mock file write
        mock_file = AsyncMock()
        mock_file_ctx = AsyncMock()
        mock_file_ctx.__aenter__.return_value = mock_file
        mock_sftp.open = MagicMock(return_value=mock_file_ctx)

        # Mock run_command for sbatch
        mock_ssh_manager.run_command = AsyncMock(return_value=("Submitted batch job 12345", "", 0))

        payload = {
            "job_name": "test_job",
            "working_dir": "/srv/hpc-link/data/jobs",
            "commands": ["echo hello"]
        }

        response = self.client.post("/api/jobs/submit", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job_id"], "12345")

        # Verify sbatch command
        mock_ssh_manager.run_command.assert_called_with("sbatch /srv/hpc-link/data/jobs/test_job.sh")

    @patch('app.routers.jobs.ssh_manager')
    def test_get_job_status(self, mock_ssh_manager):
        # Mock squeue output
        # %i|%j|%P|%T|%M|%D|%R
        # %i|%j|%P|%T|%M|%D|%R
        squeue_out = "12345|test_job|partition-a|RUNNING|1:00|1|None\n"
        mock_ssh_manager.run_command = AsyncMock(return_value=(squeue_out, "", 0))

        response = self.client.get("/api/jobs/12345")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["job_id"], "12345")
        self.assertEqual(data["state"], "RUNNING")

    @patch('app.routers.jobs.ssh_manager')
    def test_cancel_job(self, mock_ssh_manager):
        mock_ssh_manager.run_command = AsyncMock(return_value=("", "", 0))

        response = self.client.delete("/api/jobs/12345")
        self.assertEqual(response.status_code, 200)
        mock_ssh_manager.run_command.assert_called_with("scancel 12345")

    @patch('app.routers.jobs.ssh_manager')
    def test_list_jobs(self, mock_ssh_manager):
        squeue_out = "123|job1|p|R|0:10|1|None\n456|job2|p|PD|0:00|1|Resources"
        mock_ssh_manager.run_command = AsyncMock(return_value=(squeue_out, "", 0))

        response = self.client.get("/api/jobs/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["job_id"], "123")
        self.assertEqual(data[1]["job_id"], "456")

    @patch('app.routers.jobs.ssh_manager')
    @patch('app.config.get_settings')
    def test_stream_job_logs(self, mock_settings, mock_ssh_manager):
        mock_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # 1. Mock scontrol output with VALID path
        # StdOut=/path/to/log
        scontrol_out = "JobId=123 Name=test WorkDir=/srv/hpc-link/data StdOut=/srv/hpc-link/data/slurm-123.out"
        mock_ssh_manager.run_command = AsyncMock(return_value=(scontrol_out, "", 0))

        # 2. Mock SFTP exists (True)
        mock_sftp = AsyncMock()
        mock_sftp.exists.return_value = True
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # 3. Mock create_process for tail -f
        mock_process = MagicMock()

        # Mock async iterator for stdout
        async def mock_stdout_iter():
            yield "Line 1\n"
            yield "Line 2\n"

        mock_process.stdout = mock_stdout_iter()

        mock_proc_ctx = AsyncMock()
        mock_proc_ctx.__aenter__.return_value = mock_process

        mock_conn = MagicMock()
        mock_conn.create_process.return_value = mock_proc_ctx
        mock_ssh_manager.connect = AsyncMock(return_value=mock_conn)

        # Test WebSocket
        with self.client.websocket_connect("/api/jobs/123/logs") as websocket:
            messages = []
            try:
                while True:
                    msg = websocket.receive_text()
                    messages.append(msg)
            except:
                pass # Disconnect

            self.assertIn("Line 1\n", messages)
            self.assertIn("Line 2\n", messages)

    @patch('app.routers.jobs.ssh_manager')
    def test_get_job_status_completed_or_unknown(self, mock_ssh_manager):
        # Case 1: "Invalid job id" in stderr
        mock_ssh_manager.run_command = AsyncMock(return_value=("", "slurm_load_jobs error: Invalid job id specified", 1))

        response = self.client.get("/api/jobs/99999")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["state"], "COMPLETED_OR_UNKNOWN")
        self.assertIn("finished", data["reason"])

    @patch('app.routers.jobs.ssh_manager')
    def test_get_job_status_empty_output(self, mock_ssh_manager):
        # Case 2: Empty stdout, no error
        mock_ssh_manager.run_command = AsyncMock(return_value=("", "", 0))

        response = self.client.get("/api/jobs/88888")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["state"], "COMPLETED_OR_UNKNOWN")
        self.assertEqual(data["reason"], "No output")

    @patch('app.routers.jobs.ssh_manager')
    def test_submit_job_missing_working_dir(self, mock_ssh_manager):
        payload = {
            "job_name": "test_job",
            "commands": ["echo hello"]
            # missing working_dir
        }
        response = self.client.post("/api/jobs/submit", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("working_dir", response.json()["detail"])

    @patch('app.routers.jobs.ssh_manager')
    @patch('app.config.get_settings')
    def test_submit_job_sbatch_failure(self, mock_settings, mock_ssh_manager):
        # Ensure validation passes
        mock_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        # Mock file write
        mock_file_ctx = AsyncMock()
        mock_file_ctx.__aenter__.return_value = AsyncMock()
        mock_sftp.open = MagicMock(return_value=mock_file_ctx)

        # sbatch fails
        mock_ssh_manager.run_command = AsyncMock(return_value=("", "some sbatch error", 1))

        payload = {
            "job_name": "fail_job",
            "working_dir": "/srv/hpc-link/data/tmp",
            "commands": ["echo hello"]
        }

        response = self.client.post("/api/jobs/submit", json=payload)
        self.assertEqual(response.status_code, 500)
        self.assertIn("sbatch failed", response.json()["detail"])

    @patch('app.routers.jobs.ssh_manager')
    @patch('app.config.get_settings')
    def test_submit_job_parsing_failure(self, mock_settings, mock_ssh_manager):
        mock_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        mock_file_ctx = AsyncMock()
        mock_file_ctx.__aenter__.return_value = AsyncMock()
        mock_sftp.open = MagicMock(return_value=mock_file_ctx)

        # sbatch succeeds but output is weird
        mock_ssh_manager.run_command = AsyncMock(return_value=("Unexpected output format", "", 0))

        payload = {
            "job_name": "weird_job",
            "working_dir": "/srv/hpc-link/data/tmp",
            "commands": ["echo hello"]
        }

        response = self.client.post("/api/jobs/submit", json=payload)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Could not parse job ID", response.json()["detail"])

    @patch('app.routers.jobs.ssh_manager')
    @patch('app.config.get_settings')
    def test_submit_job_jail_violation(self, mock_settings, mock_ssh_manager):
        mock_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # Valid working dir, but invalid output path
        payload = {
            "job_name": "bad_job",
            "working_dir": "/srv/hpc-link/data",
            "output_path": "/etc/shadow",
            "commands": ["echo hello"]
        }

        response = self.client.post("/api/jobs/submit", json=payload)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Access denied", response.json()["detail"])

    @patch('app.routers.jobs.ssh_manager')
    @patch('app.config.get_settings')
    def test_stream_job_logs_jail_violation(self, mock_settings, mock_ssh_manager):
        mock_settings.return_value.hpc_data_root = "/srv/hpc-link/data"

        # Mock scontrol returning bad path
        scontrol_out = "JobId=666 Name=evil StdOut=/etc/passwd"
        mock_ssh_manager.run_command = AsyncMock(return_value=(scontrol_out, "", 0))

        # Mock SFTP (shouldn't be reached if validation fails first, but setup anyway)
        mock_sftp = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__.return_value = mock_sftp
        mock_ssh_manager.open_sftp = AsyncMock(return_value=mock_conn_ctx)

        with self.client.websocket_connect("/api/jobs/666/logs") as websocket:
            msg = websocket.receive_text()
            self.assertIn("Security violation", msg)
            # Socket should close
            try:
                websocket.receive_text()
            except:
                pass # Expected close

if __name__ == '__main__':
    unittest.main()
