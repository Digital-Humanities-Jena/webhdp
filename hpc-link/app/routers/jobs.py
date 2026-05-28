from fastapi import APIRouter, HTTPException, Depends, WebSocket, Request
from typing import List, Optional
from pydantic import BaseModel
import re
import asyncio
import shlex

from app.ssh_manager import ssh_manager
from app.schemas.job import JobConfig
from app.services.job_templating import job_template_service
from app.security import (
    enforce_allocation_policy,
    get_api_key,
    get_request_user,
    get_ws_api_key,
    get_ws_request_user,
    parse_slurm_time_to_minutes,
    require_admin_user,
    validate_path,
)
from app.limiter import limiter
from app.metrics import JOB_SUBMISSIONS

router = APIRouter(prefix="/jobs", tags=["Jobs"])
job_owner_registry: dict[str, str] = {}
_JOB_ID_RE = re.compile(r"^[0-9]+(?:_[0-9]+)?(?:\.[0-9]+)?$")

class JobSubmissionResponse(BaseModel):
    job_id: str
    message: str
    script_path: str

class JobStatus(BaseModel):
    job_id: str
    name: str = "unknown"
    partition: str = "unknown"
    state: str = "UNKNOWN"
    time_used: str = "0:00"
    nodes: int = 0
    reason: Optional[str] = None


def _ensure_job_access(username: str, is_admin: bool, job_id: str) -> None:
    _validate_job_id(job_id)
    if is_admin:
        return
    owner = job_owner_registry.get(job_id)
    if owner != username:
        raise HTTPException(status_code=403, detail="Access denied for this job")


def _validate_job_id(job_id: str) -> str:
    text = str(job_id or "").strip()
    if not _JOB_ID_RE.fullmatch(text):
        raise HTTPException(status_code=400, detail="Invalid job id")
    return text

@router.post("/submit", response_model=JobSubmissionResponse, dependencies=[Depends(get_api_key)])
@limiter.limit("5/minute")
async def submit_job(request: Request, config: JobConfig):
    """
    Generate an sbatch script, upload it, and submit it to SLURM.
    """
    current_user = get_request_user(request)
    require_admin_user(current_user)
    enforce_allocation_policy(
        current_user,
        partition=config.partition,
        gpu_type=config.gpu_type,
        gpu_count=max(1, config.gpu_count) if config.gpu_count > 0 else 1,
        duration_minutes=parse_slurm_time_to_minutes(config.time_limit),
    )

    # 1. Render Script
    script_content = job_template_service.render_sbatch(config)

    # 2. Determine Script Path
    # Use working_dir if provided, else use hpc_data_root + /jobs
    working_dir = config.working_dir
    if not working_dir:
         # Fallback to a default jobs directory
         # Ideally we should read this from config settings to be safe
         # For now let's error if working_dir is not explicit, or use a default.
         raise HTTPException(status_code=400, detail="working_dir must be specified")

    working_dir = validate_path(working_dir)
    script_name = f"{config.job_name}.sh"
    script_path = f"{working_dir}/{script_name}"

    # Security: Validate Output/Error Paths
    # If paths are relative, they are relative to working_dir (which is safe).
    # If absolute, they must be inside jail.
    # validate_path handles absolute paths. For relative, we need to join with base.

    # We pass working_dir as base_path for relative resolution?
    # validate_path uses hpc_data_root as default base.
    # If config.output_path is "slurm.out", validate_path("slurm.out") -> /work/.../slurm.out (if based on root)
    # BUT SLURM interprets relative paths relative to working_dir.
    # So we should validate them relative to working_dir.

    # helper to validate relative to working_dir
    def validate_job_path(p: str, base: str):
        # If absolute, validate_path checks against hpc_data_root (global jail)
        # If relative, join with working_dir and validate
        if p.startswith("/"):
            return validate_path(p)
        else:
            return validate_path(f"{base}/{p}")

    config.output_path = validate_job_path(config.output_path, working_dir)
    config.error_path = validate_job_path(config.error_path, working_dir)

    # 1. Render Script
    script_content = job_template_service.render_sbatch(config)

    # 3. Upload Script
    try:
        async with await ssh_manager.open_sftp() as sftp:
            # Ensure directory exists? user should create it or we do it?
            # Let's assume it exists or mkdir -p logic elsewhere.
            async with sftp.open(script_path, 'w') as f:
                await f.write(script_content)
    except Exception as e:
        JOB_SUBMISSIONS.labels(status="failed").inc()
        raise HTTPException(status_code=500, detail=f"Failed to upload script: {e}")

    # 4. Submit Job
    # sbatch /path/to/script.sh
    # Output: Submitted batch job 12345
    command = f"sbatch {shlex.quote(script_path)}"
    stdout, stderr, exit_code = await ssh_manager.run_command(command)

    if exit_code != 0:
        JOB_SUBMISSIONS.labels(status="failed").inc()
        raise HTTPException(status_code=500, detail=f"sbatch failed: {stderr}")

    # Parse Job ID
    match = re.search(r"Submitted batch job (\d+)", stdout)
    if not match:
        JOB_SUBMISSIONS.labels(status="failed").inc()
        raise HTTPException(status_code=500, detail=f"Could not parse job ID from sbatch output: {stdout}")

    job_id = match.group(1)
    job_owner_registry[job_id] = current_user.username
    JOB_SUBMISSIONS.labels(status="success").inc()

    return JobSubmissionResponse(
        job_id=job_id,
        message="Job submitted successfully",
        script_path=script_path
    )

@router.get("/{job_id}", response_model=JobStatus, dependencies=[Depends(get_api_key)])
async def get_job_status(request: Request, job_id: str):
    """
    Get status of a specific job using squeue.
    """
    # squeue --job <id> --json
    # Or parsing default format. JSON is robust if available.
    # Let's use formatted output for broader compatibility:
    # squeue -j <id> -o "%i|%j|%P|%T|%M|%D|%R" --noheader

    current_user = get_request_user(request)
    _ensure_job_access(current_user.username, current_user.is_admin, job_id)

    job_id = _validate_job_id(job_id)
    command = f"squeue -j {shlex.quote(job_id)} -o '%i|%j|%P|%T|%M|%D|%R' --noheader"
    stdout, stderr, exit_code = await ssh_manager.run_command(command)

    if exit_code != 0:
        # Job might have finished and is no longer in squeue.
        # Fallback to sacct could be implemented here.
        # For now, return a 'COMPLETED/UNKNOWN' state or 404
        if "Invalid job id" in stderr:
             # Try SACCT? Or just return unknown
             return JobStatus(
                 job_id=job_id,
                 state="COMPLETED_OR_UNKNOWN",
                 reason="Not found in squeue (might be finished)"
             )
        raise HTTPException(status_code=500, detail=f"squeue failed: {stderr}")

    if not stdout.strip():
         return JobStatus(job_id=job_id, state="COMPLETED_OR_UNKNOWN", reason="No output")

    try:
        parts = stdout.strip().split('|')
        # %i|%j|%P|%T|%M|%D|%R
        # id|name|partition|state|time|nodes|reason
        return JobStatus(
            job_id=parts[0],
            name=parts[1],
            partition=parts[2],
            state=parts[3],
            time_used=parts[4],
            nodes=int(parts[5]),
            reason=parts[6]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse squeue output: {e}")

@router.delete("/{job_id}", dependencies=[Depends(get_api_key)])
async def cancel_job(request: Request, job_id: str):
    """
    Cancel a running job.
    """
    current_user = get_request_user(request)
    _ensure_job_access(current_user.username, current_user.is_admin, job_id)

    job_id = _validate_job_id(job_id)
    command = f"scancel {shlex.quote(job_id)}"
    stdout, stderr, exit_code = await ssh_manager.run_command(command)

    if exit_code != 0:
        raise HTTPException(status_code=500, detail=f"scancel failed: {stderr}")

    return {"message": f"Job {job_id} cancelled"}

@router.get("/", response_model=List[JobStatus], dependencies=[Depends(get_api_key)])
async def list_jobs(request: Request):
    """
    List all jobs for the current user.
    """
    # Get current user first? OR assumes squeue shows user jobs.
    # squeue --me -o ... works

    command = "squeue --me -o '%i|%j|%P|%T|%M|%D|%R' --noheader"
    stdout, stderr, exit_code = await ssh_manager.run_command(command)

    if exit_code != 0:
        raise HTTPException(status_code=500, detail=f"squeue failed: {stderr}")

    current_user = get_request_user(request)
    jobs = []
    for line in stdout.strip().split('\n'):
        if not line: continue
        try:
            parts = line.split('|')
            if not current_user.is_admin and job_owner_registry.get(parts[0]) != current_user.username:
                continue
            jobs.append(JobStatus(
                job_id=parts[0],
                name=parts[1],
                partition=parts[2],
                state=parts[3],
                time_used=parts[4],
                nodes=int(parts[5]),
                reason=parts[6]
            ))
        except:
            continue

    return jobs

@router.websocket("/{job_id}/logs")
async def stream_job_logs(websocket: WebSocket, job_id: str, api_key: str = Depends(get_ws_api_key)):
    """
    Stream output logs for a running or completed job.
    """
    current_user = get_ws_request_user(websocket)
    job_id = _validate_job_id(job_id)
    if not current_user.is_admin and job_owner_registry.get(job_id) != current_user.username:
        await websocket.accept()
        await websocket.send_text("Error: Access denied for this job")
        await websocket.close()
        return

    await websocket.accept()

    try:
        # 1. Resolve Output Path
        # We need to know where the stdout/stderr file is.
        # This is tricky without database state.
        # Strategy: "scontrol show job {id}" provides WorkDir and StdOut.

        command = f"scontrol show job {shlex.quote(job_id)} -o"
        stdout, stderr, exit_code = await ssh_manager.run_command(command)

        if exit_code != 0:
             await websocket.send_text(f"Error: Could not find job {job_id}")
             return

        # Parse StdOut=...
        # Output format: JobId=123 Name=... WorkDir=/... StdOut=/path/to/slurm-123.out ...
        match = re.search(r"StdOut=([^\s]+)", stdout)
        if not match:
             # Default fallback?
             await websocket.send_text("Error: Could not determine output file path")
             return

        log_path = match.group(1)

        # Security: Validate Path (Jail)
        try:
            log_path = validate_path(log_path)
        except HTTPException as e:
            await websocket.send_text(f"Security violation: Log path outside allowed directory ({log_path})")
            return

        # 2. Check if file exists
        async with await ssh_manager.open_sftp() as sftp:
             # Wait loop for file creation?
             retries = 10
             while retries > 0:
                 if await sftp.exists(log_path):
                     break
                 await asyncio.sleep(1)
                 retries -= 1

             if not await sftp.exists(log_path):
                 await websocket.send_text("Log file not found (job might be queuing)")
                 # Keep connection open?

        # 3. Tail Loop
        # We use a simple polling tail over SFTP or 'tail -f' via SSH command?
        # 'tail -f' via SSH is more efficient and handles 'follow' better.

        # open_shell or just run_command with a stream?
        # ssh_manager.create_process allows interacting with stdin/stdout/stderr

        conn = await ssh_manager.connect()
        async with conn.create_process(f"tail -f {shlex.quote(log_path)}") as process:
            # Relay output
            async for line in process.stdout:
                await websocket.send_text(line)

    except Exception as e:
        await websocket.send_text(f"Connection error: {e}")
    finally:
        await websocket.close()
