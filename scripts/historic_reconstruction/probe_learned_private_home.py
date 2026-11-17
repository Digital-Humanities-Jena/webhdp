#!/usr/bin/env python3
"""Run inside the actual contained runtime; no model inference is performed."""
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("launcher", "/opt/historic-learned/learned_entrypoint.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
before = dict(os.environ)
config = "/opt/historic-learned/geolocalization-operator-config.json"
child = launcher.child_environment("geolocalization", config)
private_home = Path(child["HOME"])
assert private_home.parent == Path("/tmp") and private_home.name.startswith("webhdp-learned-home-")
assert private_home.stat().st_mode & 0o777 == 0o700
assert (private_home / ".cache/colmap").is_symlink()
assert (private_home / ".cache/colmap").resolve() == Path("/opt/historic-learned/geolocation/colmap-cache")
assert dict(os.environ) == before
print(json.dumps({"success": True, "scope": "Actual contained runtime private-home/cache probe; no scientific inference",
                  "parent_environment_unchanged": True, "private_home": str(private_home),
                  "cache_target": str((private_home / ".cache/colmap").resolve()), "mode": "0700"}))
