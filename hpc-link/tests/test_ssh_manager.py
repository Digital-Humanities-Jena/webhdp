import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from app.ssh_manager import SSHManager

class TestSSHManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        with patch('app.ssh_manager.get_settings') as mock_settings:
            mock_settings.return_value.hpc_host = "hpc-login"
            mock_settings.return_value.hpc_user = "user"
            mock_settings.return_value.ssh_key_path = "/tmp/key"
            mock_settings.return_value.default_partition = "partition-b"
            mock_settings.return_value.default_gpu_type = "a100"
            mock_settings.return_value.default_gpu_count = 1
            mock_settings.return_value.default_time_limit = "01:00:00"
            self.manager = SSHManager()

    @patch('app.ssh_manager.SSHManager.connect')
    async def test_allocate_gpu_and_run(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Mock result of conn.run
        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_conn.run = AsyncMock(return_value=mock_result)

        stdout, stderr, exit_code = await self.manager.allocate_gpu_and_run("nvidia-smi")

        self.assertEqual(stdout, "output")
        # Verify srun command
        expected_cmd = "srun --partition=partition-b --gres=gpu:a100:1 --time=01:00:00 --job-name=hpc-link nvidia-smi"
        mock_conn.run.assert_called_with(expected_cmd, check=False)

    async def test_allocate_gpu_rejects_unsafe_gpu_type(self):
        with self.assertRaises(HTTPException) as context:
            await self.manager.allocate_gpu_and_run("nvidia-smi", gpu_type="a100;id")

        self.assertEqual(context.exception.status_code, 400)

if __name__ == '__main__':
    unittest.main()
