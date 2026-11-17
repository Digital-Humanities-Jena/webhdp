#!/usr/bin/env python3
"""Contained imports, compiled capability checks and immutable pins; no inference."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys

stage = sys.argv[1]
if stage not in {"original_sfm", "geolocalization", "dense_intrinsics"}:
    raise ValueError("Unsupported learned preflight stage")
if len(sys.argv) == 2:
    spec = importlib.util.spec_from_file_location("launcher", "/opt/historic-learned/learned_entrypoint.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    config = f"/opt/historic-learned/{stage}-operator-config.json"
    # Exercise the same fixed prefix and child environment used by native runs.
    actual_stage, actual_config, command = launcher.stage_command([
        "env", "HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG=" + config,
        "python", "/app/component_runner.py", "upstream-" + stage])
    child = launcher.child_environment(actual_stage, actual_config)
    os.execve(command[0], [command[0], __file__, stage, "--child"], child)
assert sys.argv[2:] == ["--child"]
sys.path.insert(0, "/app")
import upstream

output = Path("/verification") / stage
output.mkdir()
private_home = Path(os.environ["HOME"])
assert private_home.parent == Path("/tmp") and private_home.name.startswith("webhdp-learned-home-")
assert private_home.stat().st_mode & 0o777 == 0o700
if stage == "geolocalization":
    assert (private_home / ".cache/colmap").resolve() == Path("/opt/historic-learned/geolocation/colmap-cache")
config = upstream.load_config(stage)
environment = upstream._environment(config, output)
assert int(environment["OMP_NUM_THREADS"]) <= 2
upstream._preflight(stage, config, environment, output, {"skip_doppelgangers": False})
upstream._assert_runtime_unchanged(config)
proof = {"success": True, "stage": stage, "completed_at": datetime.now(timezone.utc).isoformat(),
         "scope": "Actual SIF learned-stage imports, CUDA capability checks, private home/cache and unchanged pins",
         "scientific_inference_executed": False, "cpu_thread_limit": int(environment["OMP_NUM_THREADS"]),
         "source_sha256": config["source"]["sha256"], "config_sha256": config["_config_sha256"],
         "python_sha256": config["python"]["sha256"], "private_home": str(private_home),
         "runtime_pins": {"python_sha256": config["python"]["sha256"],
                          "dependencies": [row["sha256"] for row in config.get("dependencies", [])],
                          "assets": {name: row["sha256"] for name, row in config.get("assets", {}).items()}},
         "skip_doppelgangers": False}
(output / "verification.json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps(proof))
