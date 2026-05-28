import os
import shutil
import time
import logging
from pathlib import Path
from threading import Thread
from datetime import datetime, timedelta
import secrets
from typing import Optional


logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session directories with automatic cleanup"""

    def __init__(
        self,
        session_timeout=1800,
        flask_session_dir: Optional[str] = None,
        cleanup_flask_sessions: bool = False,
        artifact_cleanup_enabled: bool = False,
        artifact_retention_seconds: int | float | None = None,
        cleanup_interval: int | float = 300,
    ):
        """
        Initialize session manager.

        Args:
            session_timeout: Session timeout in seconds (int/float) or timedelta object
            flask_session_dir: Optional Flask-Session storage directory
            cleanup_flask_sessions: If True, cleanup expired files inside flask_session_dir
            artifact_cleanup_enabled: If True, remove old bulky session artifacts
            artifact_retention_seconds: Age threshold for artifact cleanup
            cleanup_interval: Seconds between cleanup checks
        """
        # Convert timedelta to seconds if needed
        if isinstance(session_timeout, timedelta):
            self.session_timeout = int(session_timeout.total_seconds())
        else:
            self.session_timeout = session_timeout

        self.flask_session_dir = Path(flask_session_dir) if flask_session_dir else None
        self.cleanup_flask_sessions = bool(cleanup_flask_sessions and self.flask_session_dir)
        self.artifact_cleanup_enabled = bool(artifact_cleanup_enabled)
        self.artifact_retention_seconds = int(
            artifact_retention_seconds if artifact_retention_seconds is not None else self.session_timeout
        )
        self.cleanup_interval = int(cleanup_interval)  # Check every 5 minutes by default
        self._start_cleanup_thread()

    def create_session_dirs(self):
        """Creates temporary directories for a session."""
        # Use shared path instead of system temp
        shared_base = os.environ.get("SHARED_SESSION_PATH", "/tmp")
        session_dir = os.path.join(shared_base, f"hdp_session_{secrets.token_hex(4)}")
        os.makedirs(session_dir, exist_ok=True)
        os.chmod(session_dir, 0o755)  # More permissive for host access

        hdpc_path = os.path.join(session_dir, "session.hdpc")
        data_out_path = os.path.join(session_dir, "outputs")
        uploads_path = os.path.join(session_dir, "uploads")

        os.makedirs(data_out_path, exist_ok=True)
        os.makedirs(uploads_path, exist_ok=True)

        os.chmod(data_out_path, 0o755)
        os.chmod(uploads_path, 0o755)

        logger.info(f"Session dirs created at {session_dir}")
        return hdpc_path, data_out_path, uploads_path, session_dir

    def _start_cleanup_thread(self):
        """Starts background thread for cleaning up expired sessions"""

        def cleanup_worker():
            while True:
                try:
                    self._cleanup_expired_sessions()
                except Exception as e:
                    logger.error(f"Error in session cleanup: {e}")
                time.sleep(self.cleanup_interval)

        thread = Thread(target=cleanup_worker, daemon=True)
        thread.start()
        logger.info("Session cleanup thread started")

    def _cleanup_expired_sessions(self):
        """Removes session contents older than session_timeout, but preserves session.hdpc"""
        # Clean up HDP sessions from the shared path
        shared_base = os.environ.get("SHARED_SESSION_PATH", "/tmp")
        current_time = time.time()
        artifact_cutoff_time = current_time - self.artifact_retention_seconds

        if self.artifact_cleanup_enabled:
            # Find and remove expired HDP session artifacts. This is disabled by
            # default for deployments so auth/session expiry never implies data
            # loss. Operators must opt in with a separate retention window.
            for item in Path(shared_base).glob("hdp_session_*"):
                if item.is_dir():
                    try:
                        dir_mtime = item.stat().st_mtime
                        if dir_mtime < artifact_cutoff_time:
                            self._selective_cleanup(item)
                    except Exception as e:
                        logger.warning(f"Could not clean up session {item}: {e}")

        # Only cleanup Flask session cache when explicitly enabled.
        # Never delete the root session directory itself to avoid runtime cache write errors.
        if self.cleanup_flask_sessions and self.flask_session_dir:
            cutoff_time = current_time - self.session_timeout
            self._cleanup_flask_session_files(cutoff_time)

    def _selective_cleanup(self, session_dir: Path):
        """Deletes everything in session_dir except session.hdpc"""
        has_deleted_anything = False
        for entry in session_dir.iterdir():
            if entry.name == "session.hdpc":
                continue

            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    os.remove(entry)
                has_deleted_anything = True
            except Exception as e:
                logger.debug(f"Failed to remove {entry} during selective cleanup: {e}")

        if has_deleted_anything:
            logger.info(f"Selectively cleaned up session: {session_dir} (preserved .hdpc)")

    def _cleanup_flask_session_files(self, cutoff_time: float):
        """Delete expired cache entries inside the configured Flask session directory."""
        try:
            self.flask_session_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not ensure Flask session directory exists {self.flask_session_dir}: {e}")
            return

        removed = 0
        for entry in self.flask_session_dir.iterdir():
            try:
                if entry.stat().st_mtime >= cutoff_time:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink(missing_ok=True)
                removed += 1
            except Exception as e:
                logger.warning(f"Could not clean Flask session cache entry {entry}: {e}")

        if removed:
            logger.info(f"Cleaned up {removed} expired Flask session cache entries in {self.flask_session_dir}")
