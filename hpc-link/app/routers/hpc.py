"""HPC interaction endpoints."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.ssh_manager import ssh_manager
from app.config import get_settings
from app.limiter import limiter
from app.security import (
    enforce_allocation_policy,
    get_request_user,
    parse_slurm_time_to_minutes,
    require_admin_user,
)

router = APIRouter(prefix="/hpc", tags=["HPC"])


class CommandRequest(BaseModel):
    """Request to execute a command on the HPC."""
    command: str
    timeout: float = 60.0


class CommandResponse(BaseModel):
    """Response from command execution."""
    stdout: str
    stderr: str
    exit_code: int
    success: bool


class GPUAllocationRequest(BaseModel):
    """Request to allocate a GPU and run a command."""
    command: str
    partition: Optional[str] = None
    gpu_type: Optional[str] = None
    gpu_count: Optional[int] = None
    time_limit: Optional[str] = None
    timeout: float = 300.0


class NvidiaSmiResponse(BaseModel):
    """Response from nvidia-smi command."""
    success: bool
    output: str
    gpu_name: Optional[str] = None
    gpu_memory: Optional[str] = None
    partition: str
    error: Optional[str] = None


@router.post("/execute", response_model=CommandResponse)
@limiter.limit("10/minute")
async def execute_command(request: Request, cmd_request: CommandRequest):
    """Execute a command on the HPC login node."""
    require_admin_user(get_request_user(request))
    try:
        stdout, stderr, exit_code = await ssh_manager.run_command(
            cmd_request.command,
            timeout=cmd_request.timeout
        )
        return CommandResponse(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            success=exit_code == 0
        )
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/allocate", response_model=CommandResponse)
@limiter.limit("10/minute")
async def allocate_gpu_and_run(request: Request, cmd_request: GPUAllocationRequest):
    """Allocate a GPU via SLURM and execute a command."""
    settings = get_settings()
    current_user = get_request_user(request)
    require_admin_user(current_user)
    effective_partition = cmd_request.partition or settings.default_partition
    effective_gpu_type = cmd_request.gpu_type or settings.default_gpu_type
    effective_gpu_count = cmd_request.gpu_count or settings.default_gpu_count
    effective_time_limit = cmd_request.time_limit or settings.default_time_limit
    effective_minutes = parse_slurm_time_to_minutes(effective_time_limit)
    enforce_allocation_policy(
        current_user,
        partition=effective_partition,
        gpu_type=effective_gpu_type,
        gpu_count=effective_gpu_count,
        duration_minutes=effective_minutes,
    )

    try:
        stdout, stderr, exit_code = await ssh_manager.allocate_gpu_and_run(
            command=cmd_request.command,
            partition=effective_partition,
            gpu_type=effective_gpu_type,
            gpu_count=effective_gpu_count,
            time_limit=effective_time_limit,
            timeout=cmd_request.timeout
        )
        return CommandResponse(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            success=exit_code == 0
        )
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nvidia-smi", response_model=NvidiaSmiResponse)
async def run_nvidia_smi(
    request: Request,
    partition: Optional[str] = None,
    gpu_type: Optional[str] = None
):
    """
    Allocate a GPU and run nvidia-smi to verify GPU access.

    This is the primary verification endpoint that proves:
    1. VPN connectivity works
    2. SSH connection to HPC works
    3. GPU allocation via SLURM works
    4. GPU is accessible and functional
    """
    settings = get_settings()
    partition = partition or settings.default_partition
    gpu_type = gpu_type or settings.default_gpu_type
    effective_minutes = parse_slurm_time_to_minutes(settings.default_time_limit)
    enforce_allocation_policy(
        get_request_user(request),
        partition=partition,
        gpu_type=gpu_type,
        gpu_count=settings.default_gpu_count,
        duration_minutes=effective_minutes,
    )

    try:
        stdout, stderr, exit_code = await ssh_manager.allocate_gpu_and_run(
            command="nvidia-smi",
            partition=partition,
            gpu_type=gpu_type,
            timeout=120.0  # GPU allocation can take time
        )

        if exit_code != 0:
            return NvidiaSmiResponse(
                success=False,
                output=stderr or stdout,
                partition=partition,
                error=f"nvidia-smi failed with exit code {exit_code}"
            )

        # Parse GPU info from nvidia-smi output
        gpu_name = None
        gpu_memory = None
        for line in stdout.split('\n'):
            if 'NVIDIA' in line and ('RTX' in line or 'A100' in line or 'A5000' in line):
                # Extract GPU name from the nvidia-smi output
                parts = line.split('|')
                if len(parts) >= 2:
                    # Typical line: |   0  NVIDIA GeForce RTX 3090  On   | ...
                    gpu_info = parts[1].strip().split()
                    if gpu_info and gpu_info[0].isdigit():
                        gpu_info = gpu_info[1:]
                    if gpu_info and gpu_info[-1] in ('On', 'Off'):
                        gpu_info = gpu_info[:-1]
                    gpu_name = ' '.join(gpu_info)
                    gpu_name = gpu_name if gpu_name else None
            if 'MiB' in line and '/' in line:
                # Memory usage line
                parts = line.split('|')
                for part in parts:
                    if 'MiB' in part and '/' in part:
                        gpu_memory = part.strip()
                        break

        return NvidiaSmiResponse(
            success=True,
            output=stdout,
            gpu_name=gpu_name,
            gpu_memory=gpu_memory,
            partition=partition
        )

    except TimeoutError:
        return NvidiaSmiResponse(
            success=False,
            output="",
            partition=partition,
            error="GPU allocation timed out - queue may be busy"
        )
    except Exception as e:
        return NvidiaSmiResponse(
            success=False,
            output="",
            partition=partition,
            error=str(e)
        )


@router.get("/partitions")
async def list_gpu_partitions():
    """List available GPU partitions and their status."""
    try:
        settings = get_settings()
        partition_filter = f"-p {settings.sinfo_partitions} " if settings.sinfo_partitions else ""
        stdout, stderr, exit_code = await ssh_manager.run_command(
            f"sinfo {partition_filter}--format='%P|%N|%a|%D|%G|%t' --noheader"
        )

        if exit_code != 0:
            raise HTTPException(status_code=500, detail=stderr)

        partitions = []
        for line in stdout.strip().split('\n'):
            if line:
                parts = line.split('|')
                if len(parts) >= 6:
                    partitions.append({
                        "partition": parts[0].strip().rstrip('*'),
                        "nodes": parts[1].strip(),
                        "available": parts[2].strip(),
                        "node_count": parts[3].strip(),
                        "gres": parts[4].strip(),
                        "state": parts[5].strip()
                    })

        return {"partitions": partitions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
