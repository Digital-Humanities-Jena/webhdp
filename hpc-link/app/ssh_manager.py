"""SSH connection manager using AsyncSSH."""
import asyncio
from pathlib import Path
import shlex
from typing import Optional
import asyncssh
import structlog

from app.config import get_settings
from app.security import validate_slurm_resource_token, validate_slurm_time_string

logger = structlog.get_logger()


class SSHManager:
    """Manages SSH connections to the HPC cluster."""

    def __init__(self):
        self._connection: Optional[asyncssh.SSHClientConnection] = None
        self._lock = asyncio.Lock()
        self._settings = get_settings()

    def _resolve_known_hosts_path(self) -> str:
        known_hosts_path = (self._settings.ssh_known_hosts_path or "").strip()
        if not known_hosts_path:
            raise RuntimeError(
                "SSH host key verification requires SSH_KNOWN_HOSTS_PATH to be configured"
            )

        known_hosts = Path(known_hosts_path)
        if not known_hosts.exists():
            raise FileNotFoundError(
                f"SSH known_hosts file not found: {known_hosts_path}"
            )
        return str(known_hosts)

    async def connect(self) -> asyncssh.SSHClientConnection:
        """Establish or return existing SSH connection."""
        async with self._lock:
            if self._connection is not None and not self._connection.is_closed:
                return self._connection

            logger.info(
                "Connecting to HPC",
                host=self._settings.hpc_host,
                user=self._settings.hpc_user
            )

            # Read SSH key
            key_path = Path(self._settings.ssh_key_path)
            if not key_path.exists():
                raise FileNotFoundError(f"SSH key not found: {key_path}")

            known_hosts = self._resolve_known_hosts_path()

            try:
                self._connection = await asyncssh.connect(
                    host=self._settings.hpc_host,
                    username=self._settings.hpc_user,
                    client_keys=[str(key_path)],
                    known_hosts=known_hosts,
                    keepalive_interval=30,
                    keepalive_count_max=3,
                )
                logger.info("SSH connection established")
                return self._connection
            except Exception as e:
                logger.error("SSH connection failed", error=str(e))
                raise

    async def disconnect(self):
        """Close the SSH connection."""
        async with self._lock:
            if self._connection is not None:
                self._connection.close()
                await self._connection.wait_closed()
                self._connection = None
                logger.info("SSH connection closed")

    async def is_connected(self) -> bool:
        """Check if SSH connection is active."""
        return self._connection is not None and not self._connection.is_closed

    async def run_command(self, command: str, timeout: float = 60.0) -> tuple[str, str, int]:
        """
        Execute a command on the HPC.

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        conn = await self.connect()
        logger.info("Executing command", command=command[:100])

        try:
            result = await asyncio.wait_for(
                conn.run(command, check=False),
                timeout=timeout
            )
            return result.stdout or "", result.stderr or "", result.exit_status or 0
        except asyncio.TimeoutError:
            logger.error("Command timeout", command=command[:50])
            raise TimeoutError(f"Command timed out after {timeout}s")

    async def get_hostname(self) -> str:
        """Get the hostname of the connected HPC node."""
        stdout, _, _ = await self.run_command("hostname")
        return stdout.strip()

    async def allocate_gpu_and_run(
        self,
        command: str,
        partition: Optional[str] = None,
        gpu_type: Optional[str] = None,
        gpu_count: Optional[int] = None,
        time_limit: Optional[str] = None,
        timeout: float = 300.0
    ) -> tuple[str, str, int]:
        """
        Allocate a GPU via srun and execute a command.

        This uses srun which allocates, runs, and deallocates in one step.
        """
        settings = self._settings
        partition = validate_slurm_resource_token(partition or settings.default_partition, "partition")
        gpu_type = validate_slurm_resource_token(gpu_type or settings.default_gpu_type, "GPU type")
        gpu_count = gpu_count or settings.default_gpu_count
        time_limit = validate_slurm_time_string(time_limit or settings.default_time_limit)

        srun_cmd = (
            f"srun --partition={shlex.quote(partition)} "
            f"--gres={shlex.quote(f'gpu:{gpu_type}:{gpu_count}')} "
            f"--time={shlex.quote(time_limit)} "
            f"--job-name=hpc-link "
            f"{command}"
        )

        logger.info(
            "Allocating GPU and running command",
            partition=partition,
            gpu=f"{gpu_type}:{gpu_count}",
            command=command
        )

        return await self.run_command(srun_cmd, timeout=timeout)

    async def start_shell_session(
        self,
        cols: int = 80,
        rows: int = 24,
        term_type: str = "xterm-256color"
    ) -> asyncssh.SSHClientProcess:
        """
        Start an interactive PTY shell session.

        Returns:
            SSHClientProcess with stdin/stdout/stderr streams.
        """
        conn = await self.connect()
        logger.info("Starting interactive shell session", cols=cols, rows=rows)

        process = await conn.create_process(
            term_type=term_type,
            term_size=(cols, rows),
            encoding=None,  # Binary mode for raw terminal data
        )
        return process

    async def resize_terminal(
        self,
        process: asyncssh.SSHClientProcess,
        cols: int,
        rows: int
    ) -> None:
        """Resize the PTY terminal dimensions."""
        process.change_term_size(cols, rows)
        logger.debug("Terminal resized", cols=cols, rows=rows)

    async def connect_via_jump(
        self,
        target_host: str,
        target_user: str | None = None,
        target_port: int = 22
    ) -> asyncssh.SSHClientConnection:
        """
        Connect to a target host via the jump host (ProxyJump).

        This is useful for connecting directly to compute nodes
        that are only accessible from the login node.

        Returns:
            SSHClientConnection to the target host.
        """
        settings = self._settings

        # Use jump host settings if configured, otherwise use main HPC settings
        jump_host = settings.jump_host or settings.hpc_host
        jump_user = settings.jump_host_user or settings.hpc_user
        target_user = target_user or settings.hpc_user
        known_hosts = self._resolve_known_hosts_path()

        logger.info(
            "Connecting via jump host",
            jump_host=jump_host,
            target_host=target_host
        )

        # First, ensure we have a connection to the jump host
        jump_conn = await self.connect()

        # Create tunnel through jump host to target
        tunnel = await jump_conn.forward_local_port(
            '', 0,  # Let OS pick available port
            target_host, target_port
        )

        local_port = tunnel.get_port()
        logger.debug("Tunnel established", local_port=local_port)

        # Connect to target through the tunnel
        target_conn = await asyncssh.connect(
            host='127.0.0.1',
            port=local_port,
            username=target_user,
            client_keys=[str(Path(settings.ssh_key_path))],
            known_hosts=known_hosts,
            host_key_alias=target_host,
        )

        logger.info("Connected to target via jump host", target=target_host)
        return target_conn



    async def open_sftp(self) -> asyncssh.SFTPClient:
        """
        Open a new SFTP client session.

        Returns:
            asyncssh.SFTPClient: The SFTP client.

        Note: The caller is responsible for interacting with the SFTP client
        and managing its lifecycle (though it's tied to the connection).
        AsyncSSH SFTP clients are usually context managers.
        """
        conn = await self.connect()
        return await conn.start_sftp_client()

# Singleton instance
ssh_manager = SSHManager()
