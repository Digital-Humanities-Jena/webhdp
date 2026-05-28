"""WebSocket terminal endpoint for interactive shell sessions."""
import asyncio
import json
from typing import Optional

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
)

from app.config import get_settings
from app.ssh_manager import ssh_manager
from app.security import get_ws_api_key, get_ws_request_user, require_admin_user

logger = structlog.get_logger()

router = APIRouter(tags=["Terminal"])


class TerminalSession:
    """Manages a single terminal session."""

    def __init__(
        self,
        websocket: WebSocket,
        cols: int = 80,
        rows: int = 24
    ):
        self.websocket = websocket
        self.cols = cols
        self.rows = rows
        self.process: Optional[object] = None
        self._read_task: Optional[asyncio.Task] = None
        self._closed = False

    async def start(self) -> None:
        """Start the SSH shell session."""
        self.process = await ssh_manager.start_shell_session(
            cols=self.cols,
            rows=self.rows
        )
        logger.info("Terminal session started", cols=self.cols, rows=self.rows)

        # Start reading from SSH stdout in background
        self._read_task = asyncio.create_task(self._read_ssh_output())

    async def _read_ssh_output(self) -> None:
        """Read output from SSH and send to WebSocket."""
        try:
            while not self._closed and self.process:
                # Read available data from SSH stdout
                data = await self.process.stdout.read(4096)
                if not data:
                    break

                # Send as binary to WebSocket
                await self.websocket.send_bytes(data)
        except asyncio.CancelledError:
            logger.debug("SSH read task cancelled")
        except Exception as e:
            logger.error("Error reading SSH output", error=str(e))

    async def handle_input(self, data: bytes | str) -> None:
        """Handle input from WebSocket."""
        if self.process is None or self._closed:
            return

        if isinstance(data, str):
            # Check if it's a control message (JSON)
            try:
                msg = json.loads(data)
                if msg.get("type") == "resize":
                    await self.resize(msg.get("cols", 80), msg.get("rows", 24))
                    return
            except json.JSONDecodeError:
                # Not JSON, treat as text input
                data = data.encode('utf-8')

        # Write input to SSH stdin
        self.process.stdin.write(data)

    async def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal."""
        if self.process:
            self.cols = cols
            self.rows = rows
            await ssh_manager.resize_terminal(self.process, cols, rows)
            logger.info("Terminal resized", cols=cols, rows=rows)

    async def close(self) -> None:
        """Close the terminal session."""
        self._closed = True

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self.process:
            self.process.terminate()
            logger.info("Terminal session closed")


class MockTerminalSession:
    """Mock terminal session for testing without real SSH."""

    def __init__(self, websocket: WebSocket, cols: int = 80, rows: int = 24):
        self.websocket = websocket
        self.cols = cols
        self.rows = rows
        self._closed = False

    async def start(self) -> None:
        logger.info("Mock terminal session started")
        await self.websocket.send_bytes(b"\r\n--- HPC LINK MOCK TERMINAL ---\r\n")
        await self.websocket.send_bytes(b"Mock session (SSH unavailable or MOCK_HPC=true)\r\n")
        await self.websocket.send_bytes(b"$ ")

    async def handle_input(self, data: bytes | str) -> None:
        if self._closed:
            return

        if isinstance(data, str):
            try:
                msg = json.loads(data)
                if msg.get("type") == "resize":
                    logger.info("Mock terminal resized", cols=msg.get("cols"), rows=msg.get("rows"))
                    return
            except json.JSONDecodeError:
                data = data.encode('utf-8')

        # Simple echo for mock terminal
        if data == b'\r':
            await self.websocket.send_bytes(b"\r\n$ ")
        else:
            await self.websocket.send_bytes(data)

    async def close(self) -> None:
        self._closed = True
        logger.info("Mock terminal session closed")


@router.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket, api_key: str = Depends(get_ws_api_key)):
    """
    WebSocket endpoint for interactive terminal sessions.

    Protocol:
    - Binary messages: Raw terminal input/output
    - Text messages: JSON control messages
      - {"type": "resize", "cols": 80, "rows": 24}

    Query parameters:
    - cols: Initial terminal width (default: 80)
    - rows: Initial terminal height (default: 24)
    """
    try:
        require_admin_user(get_ws_request_user(websocket))
    except HTTPException as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=exc.detail,
        ) from exc

    settings = get_settings()

    # Get initial dimensions from query params
    cols = int(websocket.query_params.get("cols", settings.terminal_cols))
    rows = int(websocket.query_params.get("rows", settings.terminal_rows))

    await websocket.accept()
    logger.info("WebSocket terminal connection accepted", cols=cols, rows=rows)

    # Use mock session if enabled or fallback if SSH fails (handled in loop)
    if settings.mock_hpc:
        session = MockTerminalSession(websocket, cols=cols, rows=rows)
    else:
        session = TerminalSession(websocket, cols=cols, rows=rows)

    try:
        await session.start()

        # Main loop: receive from WebSocket, send to SSH
        while True:
            try:
                # Wait for message with timeout for keepalive
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=settings.terminal_timeout_seconds
                )

                if message["type"] == "websocket.disconnect":
                    break
                elif "bytes" in message:
                    await session.handle_input(message["bytes"])
                elif "text" in message:
                    await session.handle_input(message["text"])

            except asyncio.TimeoutError:
                logger.warning("Terminal session timed out")
                await websocket.close(code=1000, reason="Session timeout")
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected by client")
    except Exception as e:
        logger.error("Terminal session error", error=str(e))
        # Fallback to mock session if requested or connection failed
        if not settings.mock_hpc:
            logger.info("Starting mock session fallback after error")
            mock_session = MockTerminalSession(websocket, cols=cols, rows=rows)
            await mock_session.start()
            # Reuse the loop for the mock session
            session = mock_session
            # ... and continue the loop? Actually it's simpler to just report error for now
            # unless we want a full automatic fallback.
            # For now, let's just report the error and keep the connection open for the subagent.
            error_msg = f"\r\n[HPC Link] Connection Error: {str(e)}\r\n".encode('utf-8')
            await websocket.send_bytes(error_msg)
            await websocket.send_bytes(b"[HPC Link] Entering limited local echo mode for debugging.\r\n$ ")

            # Switch session to mock session to handle further input
            session = MockTerminalSession(websocket, cols=cols, rows=rows)
            session._closed = False # Ensure it's not closed

            # Re-enter loop logic is tricky here, so let's just continue the existing loop
            # with the replaced session object.
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                elif "bytes" in message:
                    await session.handle_input(message["bytes"])
                elif "text" in message:
                    await session.handle_input(message["text"])
        else:
            try:
                await websocket.close(code=1011, reason=str(e))
            except Exception:
                pass
    finally:
        await session.close()
