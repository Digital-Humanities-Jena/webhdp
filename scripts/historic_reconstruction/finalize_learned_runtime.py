#!/usr/bin/env python3
"""Freeze an accepted private sandbox as a SIF and verify its contained stages.

Use only after scientific runs release the sandbox. Requires at least one real
completed direct acceptance; each native installation still needs its own stage
acceptance. Compression uses two CPUs and makes no changes to source environments.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


STAGES = ("original_sfm", "geolocalization", "dense_intrinsics")


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def readable_copy_permissions(root):
    """Prepare an all-root SIF without changing any linked snapshot inode."""
    copied_files = copied_bytes = permission_changes = 0
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        current = path.stat()
        mode = stat.S_IMODE(current.st_mode)
        desired = mode | 0o444
        if path.is_dir() or mode & 0o111:
            desired |= 0o111
        if desired == mode:
            continue
        if path.is_file() and current.st_nlink > 1:
            fd, name = tempfile.mkstemp(prefix=path.name + ".permissions-", dir=path.parent)
            os.close(fd)
            temporary = Path(name)
            try:
                shutil.copy2(path, temporary)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            copied_files += 1
            copied_bytes += current.st_size
            assert path.stat().st_nlink == 1
        if path.is_file() or path.is_dir():
            path.chmod(desired)
            permission_changes += 1
    return {"linked_files_copied_before_chmod": copied_files, "copied_bytes": copied_bytes,
            "permission_changes": permission_changes, "shared_inodes_modified": False}


def check_direct_acceptance(result_path, report_path, sandbox, *, allow_runtime_revision=False):
    receipt = json.loads(result_path.read_text())
    report = json.loads(report_path.read_text())
    assert receipt["success"] is True and receipt["status"] == "completed"
    stage = receipt["summary"]["stage"]
    assert stage in STAGES and receipt["summary"]["upstream_execution"] is True
    assert report["metrics"] == receipt["summary"]
    artifact, = [row for row in receipt["artifacts"] if row["metadata"].get("role") == "report"]
    assert artifact["metadata"]["sha256"] == sha(report_path)
    assert artifact["metadata"]["bytes"] == report_path.stat().st_size
    config_path = sandbox / f"opt/historic-learned/{stage}-operator-config.json"
    config = json.loads(config_path.read_text())
    assert report["source_sha256"] == config["source"]["sha256"]
    expected = {"python_sha256": config["python"]["sha256"],
                "dependencies": [row["sha256"] for row in config.get("dependencies", [])],
                "assets": {name: row["sha256"] for name, row in config.get("assets", {}).items()}}
    pins_match = report["runtime_pins"] == expected
    assert pins_match or allow_runtime_revision, "Direct acceptance belongs to a different runtime revision"
    return {"stage": stage, "receipt": str(result_path.resolve()), "sha256": sha(result_path),
            "report": str(report_path.resolve()), "report_sha256": sha(report_path),
            "response_payload_sha256": hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "matches_staged_runtime_pins": pins_match, "runtime_pins_match": pins_match,
            "runtime_revision": None if pins_match else {"earlier_direct_pins": report["runtime_pins"],
                "candidate_image_pins": expected, "scope": "Earlier scientific evidence only; fresh final-image native execution and audit required"}}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--acceptance", action="append", type=Path, required=True)
    parser.add_argument("--acceptance-report", action="append", type=Path, required=True,
                        help="Actual research-report.json paired in the same order as --acceptance")
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--stage", action="append", choices=STAGES)
    parser.add_argument("--verification-output", type=Path,
                        help="New receipt path when adding stage preflights to an existing image")
    parser.add_argument("--verify-existing-image", action="store_true")
    parser.add_argument("--allow-runtime-revision", action="store_true",
                        help="Retain prior scientific proof explicitly as earlier-runtime evidence; native final-image acceptance is still required")
    args = parser.parse_args()
    assert os.environ.get("SLURM_JOB_ID"), "Run under the existing authorized allocation"
    assert int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) >= 2
    root = args.build_root.resolve(strict=True)
    assert (root / "staging-owner.json").is_file()
    sandbox = root / "rootfs"
    assert sandbox.is_dir() and not sandbox.is_symlink()
    verification_output = (args.verification_output or root / "verification.json").resolve()
    assert verification_output.is_relative_to(root) and not verification_output.exists(), "Retain earlier verification receipts"
    assert len(args.acceptance) == len(args.acceptance_report)
    accepted = [check_direct_acceptance(result, report, sandbox, allow_runtime_revision=args.allow_runtime_revision)
                for result, report in zip(args.acceptance, args.acceptance_report)]
    image = root / "historic-learned-a100.sif"
    source_files = [sandbox / "app/component_runner.py", sandbox / "app/upstream.py",
                    sandbox / "opt/historic-learned/learned_entrypoint.py"]
    source_files += [sandbox / f"opt/historic-learned/{stage}-operator-config.json" for stage in STAGES]
    manifest = {str(path.relative_to(sandbox)): sha(path) for path in source_files}
    metadata = root / "image-source-pins.json"
    if not args.verify_existing_image:
        assert not image.exists() and not metadata.exists(), "Use a new image path; retain earlier snapshots"
        metadata.write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
                                        "source_files": manifest, "direct_acceptances": accepted}, indent=2) + "\n")
        # Linked snapshots require copy-on-write before any permission change.
        permissions = readable_copy_permissions(sandbox)
        (root / "image-permission-preparation.json").write_text(json.dumps(permissions, indent=2) + "\n")
        squashfs = root / "historic-learned-a100.squashfs"
        assert not squashfs.exists()
        subprocess.run(["/usr/sbin/mksquashfs", str(sandbox), str(squashfs), "-noappend", "-all-root",
                        "-processors", "2", "-mem", "1G", "-comp", "gzip", "-Xcompression-level", "1", "-no-progress"], check=True)
        assert manifest == {str(path.relative_to(sandbox)): sha(path) for path in source_files}, "Runtime changed during image freeze"
        subprocess.run(["singularity", "sif", "new", str(image)], check=True)
        subprocess.run(["singularity", "sif", "add", "--datatype", "4", "--partarch", "2", "--partfs", "1",
                        "--parttype", "2", "--groupid", "1", str(image), str(squashfs)], check=True)
        subprocess.run(["singularity", "sif", "add", "--datatype", "6", "--groupid", "1", str(image), str(metadata)], check=True)
    assert image.is_file()
    pinned_metadata = json.loads(metadata.read_text())
    assert pinned_metadata["source_files"] == manifest
    image_sha = sha(image)
    (root / "historic-learned-a100.sif.sha256").write_text(image_sha + "  " + str(image) + "\n")
    probe = Path(tempfile.mkdtemp(prefix="actual-sif-preflight-", dir=root))
    probe_file = probe / "check.py"
    probe_file.write_bytes(args.probe.read_bytes())
    proofs = []
    process_environment = dict(os.environ)
    if "CUDA_VISIBLE_DEVICES" in process_environment:
        process_environment["SINGULARITYENV_CUDA_VISIBLE_DEVICES"] = process_environment["CUDA_VISIBLE_DEVICES"]
        process_environment["APPTAINERENV_CUDA_VISIBLE_DEVICES"] = process_environment["CUDA_VISIBLE_DEVICES"]
    for stage in args.stage or STAGES:
        config = json.loads((sandbox / f"opt/historic-learned/{stage}-operator-config.json").read_text())
        python = config["python"]["path"]
        command = ["singularity", "exec", "--nv", "--cleanenv", "--containall", "--no-home",
                   "--bind", str(probe) + ":/verification", str(image), "env", "OMP_NUM_THREADS=2",
                   "OPENBLAS_NUM_THREADS=2", "MKL_NUM_THREADS=2", python, "/verification/check.py", stage]
        with (probe / (stage + ".log")).open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900, env=process_environment)
        proof = json.loads((probe / stage / "verification.json").read_text())
        assert proof["success"] is True and proof["stage"] == stage
        proofs.append(proof)
    assert sha(image) == image_sha
    result = {"success": True, "scope": "Actual SIF learned-stage preflights; photographic native acceptance remains separate",
              "completed_at": datetime.now(timezone.utc).isoformat(), "slurm_job_id": os.environ["SLURM_JOB_ID"],
              "node": os.uname().nodename, "image": str(image), "sif_sha256": image_sha,
              "stages": [proof["stage"] for proof in proofs], "stage_verifications": proofs,
              "direct_acceptances": accepted, "source_pins": manifest, "probe_directory": str(probe),
              "probe_sha256": sha(probe_file), "source_environments_modified": False}
    receipt = verification_output
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"success": True, "stages": result["stages"], "sif_sha256": image_sha, "receipt": str(receipt)}))


if __name__ == "__main__":
    main()
