#!/usr/bin/env python3
"""Pre-copy frozen learned-runtime assets into a new private ART-based sandbox.

This performs file copies and pin checks only. It neither mutates a scientific
environment nor claims that an unfinished compiled backend or stage is usable.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--pin-helper", type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get("SLURM_JOB_ID"), "Run within the existing authorized allocation"
    base = args.base.resolve(strict=True)
    build = args.build_root.resolve()
    assert not build.is_relative_to(base) and not base.is_relative_to(build)
    assert (base / ".singularity.d").is_dir()
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    assert plan["target_prefix"] == "/opt/historic-learned"
    spec = importlib.util.spec_from_file_location("historic_pin_helper", args.pin_helper)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    marker = build / "staging-owner.json"
    if build.exists():
        assert marker.is_file() and json.loads(marker.read_text())["base"] == str(base)
    else:
        build.mkdir(parents=True)
        marker.write_text(json.dumps({"base": str(base), "purpose": "private learned runtime preparation"}) + "\n")
    rootfs = build / "rootfs"
    assert not rootfs.is_symlink()
    rootfs.mkdir(exist_ok=True)
    if not (build / "base-copy-complete.json").exists():
        print("Copying frozen ART base into new private sandbox", flush=True)
        subprocess.run(["rsync", "-a", "--exclude=/app/***", "--exclude=/opt/historic-learned/***",
                        str(base) + "/", str(rootfs) + "/"], check=True)
        (build / "base-copy-complete.json").write_text(json.dumps({
            "completed_at": datetime.now(timezone.utc).isoformat(), "base": str(base)}) + "\n")
    destination_root = rootfs / "opt/historic-learned"
    destination_root.mkdir(parents=True, exist_ok=True)
    checked = []
    for row in plan["copies"]:
        source = Path(row["source"])
        relative = Path(row["destination"])
        assert source.is_absolute() and source.exists()
        assert not source.resolve().is_relative_to(build) and not build.is_relative_to(source.resolve())
        assert not relative.is_absolute() and ".." not in relative.parts
        target = destination_root / relative
        assert target.resolve().is_relative_to(destination_root.resolve())
        measure = helper.tree_sha256 if source.is_dir() else digest
        assert measure(source) == row["sha256"], "Frozen source changed: " + str(source)
        print("Copying pinned entry: " + row["destination"], flush=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            target.mkdir(exist_ok=True)
            subprocess.run(["rsync", "-a", "--delete", str(source) + "/", str(target) + "/"], check=True)
        else:
            shutil.copy2(source, target)
        assert measure(target) == row["sha256"], "Copied pin mismatch: " + str(target)
        checked.append({**row, "source_pin_verified": True, "copied_pin_verified": True})
    assert args.plan.read_bytes() == plan_bytes, "Copy plan changed during staging"
    (build / "staged-plan.json").write_bytes(plan_bytes)
    receipt = {"completed_at": datetime.now(timezone.utc).isoformat(),
               "scope": "Preparation only; no compiled-backend or scientific acceptance claim",
               "rootfs": str(rootfs), "base": str(base), "copies": checked,
               "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
               "source_environments_modified": False, "pending": plan.get("pending", [])}
    (build / "staging-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"copied_entries": len(checked), "receipt": str(build / "staging-receipt.json")}), flush=True)


if __name__ == "__main__":
    main()
