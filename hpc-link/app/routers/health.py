"""Health check endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.security import get_api_key, get_request_user, require_admin_user
from app.ssh_manager import ssh_manager

router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(BaseModel):
    """Basic health check response."""
    status: str


class SSHHealthResponse(BaseModel):
    """SSH connection health response."""
    status: str
    connected: bool
    hostname: str | None = None
    error: str | None = None


class VPNHealthResponse(BaseModel):
    """VPN connectivity health response."""
    status: str
    can_reach_hpc: bool
    error: str | None = None


@router.get("", response_model=HealthResponse)
async def health_check():
    """Basic health check - always returns OK if the API is running."""
    return HealthResponse(status="ok")


@router.get("/ssh", response_model=SSHHealthResponse, dependencies=[Depends(get_api_key)])
async def ssh_health(request: Request):
    """Check SSH connection to HPC."""
    require_admin_user(get_request_user(request))
    try:
        is_connected = await ssh_manager.is_connected()
        if not is_connected:
            # Try to connect
            await ssh_manager.connect()

        hostname = await ssh_manager.get_hostname()
        return SSHHealthResponse(
            status="ok",
            connected=True,
            hostname=hostname
        )
    except Exception as e:
        return SSHHealthResponse(
            status="error",
            connected=False,
            error=str(e)
        )


@router.get("/vpn", response_model=VPNHealthResponse, dependencies=[Depends(get_api_key)])
async def vpn_health(request: Request):
    """Check VPN connectivity by attempting to reach the HPC."""
    require_admin_user(get_request_user(request))
    import asyncio

    try:
        # Try to ping the HPC login node
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "5", "hpc-login.example.edu",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.wait(), timeout=10)

        if proc.returncode == 0:
            return VPNHealthResponse(status="ok", can_reach_hpc=True)
        else:
            return VPNHealthResponse(
                status="error",
                can_reach_hpc=False,
                error="Cannot ping HPC login node"
            )
    except Exception as e:
        return VPNHealthResponse(
            status="error",
            can_reach_hpc=False,
            error=str(e)
        )


class JumpHostHealthResponse(BaseModel):
    """Jump host connectivity health response."""
    status: str
    can_reach_target: bool
    target_host: str | None = None
    target_hostname: str | None = None
    error: str | None = None


@router.get("/jump", response_model=JumpHostHealthResponse, dependencies=[Depends(get_api_key)])
async def jump_host_health(request: Request, target: str = "localhost"):
    """
    Check Jump Host connectivity by connecting to a target host through the login node.

    Query parameters:
    - target: Target hostname to connect to (default: localhost, which tests the jump connection)
    """
    require_admin_user(get_request_user(request))

    # If target is localhost, just test the basic connection
    if target == "localhost":
        try:
            is_connected = await ssh_manager.is_connected()
            if not is_connected:
                await ssh_manager.connect()

            hostname = await ssh_manager.get_hostname()
            return JumpHostHealthResponse(
                status="ok",
                can_reach_target=True,
                target_host="login_node",
                target_hostname=hostname
            )
        except Exception as e:
            return JumpHostHealthResponse(
                status="error",
                can_reach_target=False,
                target_host="login_node",
                error=str(e)
            )

    # Test actual jump host connection to a compute node
    try:
        target_conn = await ssh_manager.connect_via_jump(target)
        result = await target_conn.run("hostname", check=False)
        target_hostname = result.stdout.strip() if result.stdout else None
        target_conn.close()
        await target_conn.wait_closed()

        return JumpHostHealthResponse(
            status="ok",
            can_reach_target=True,
            target_host=target,
            target_hostname=target_hostname
        )
    except Exception as e:
        return JumpHostHealthResponse(
            status="error",
            can_reach_target=False,
            target_host=target,
            error=str(e)
        )
