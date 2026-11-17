#!/usr/bin/env python3
"""Start a fixed learned-stage contract with a private scientific-process home.

The gateway already supplies a per-invocation /tmp bind. No host home directory
is exposed or modified, and the launcher's own HOME environment is unchanged.
"""
import json
import os
from pathlib import Path
import sys
import tempfile


PREFIX = Path("/opt/historic-learned")
STAGES = {"upstream-original_sfm": "original_sfm", "upstream-geolocalization": "geolocalization",
          "upstream-dense_intrinsics": "dense_intrinsics"}


def stage_command(arguments):
    """Accept only the installed, fixed scientific entrypoint prefix."""
    if len(arguments) < 5 or arguments[4] not in STAGES:
        raise ValueError("Expected a fixed learned-stage component entrypoint")
    stage = STAGES[arguments[4]]
    config = str(PREFIX / (stage + "-operator-config.json"))
    expected = ["env", "HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG=" + config,
                "python", "/app/component_runner.py", arguments[4]]
    if arguments[:5] != expected:
        raise ValueError("Learned entrypoint/configuration differs from the installed contract")
    return stage, config, ["/app/component_runner.py", *arguments[4:]]


def child_environment(stage, config, *, python, temporary_root=Path("/tmp"), parent_environment=None):
    parent = dict(os.environ if parent_environment is None else parent_environment)
    if not parent.get("SINGULARITY_CONTAINER") or not Path("/.singularity.d").is_dir():
        raise RuntimeError("The learned entrypoint requires its contained Singularity runtime")
    if temporary_root != Path("/tmp") or temporary_root.is_symlink():
        raise RuntimeError("Expected the private invocation /tmp mount")
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    if not any(len(line.split()) > 4 and line.split()[4] == "/tmp" for line in mounts):
        raise RuntimeError("A separate contained /tmp mount is required")
    private_home = Path(tempfile.mkdtemp(prefix="webhdp-learned-home-", dir=temporary_root))
    if private_home.parent != temporary_root or private_home.is_symlink() or list(private_home.iterdir()):
        raise RuntimeError("Expected a new empty private scientific home")
    private_home.chmod(0o700)
    if stage == "geolocalization":
        cache = PREFIX / "geolocation/colmap-cache"
        if not cache.is_dir() or cache.is_symlink():
            raise RuntimeError("Pinned embedded COLMAP cache is unavailable")
        (private_home / ".cache").mkdir(mode=0o700)
        (private_home / ".cache/colmap").symlink_to(cache, target_is_directory=True)
    # HOME retains its normal meaning only within the spawned scientific process.
    # The launcher/host environment and host home contents remain untouched.
    child = {**parent, "HOME": str(private_home),
             "HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG": config,
             "LD_LIBRARY_PATH": str(PREFIX / "runtime-libraries-a100") + ":/.singularity.d/libs:" + str(python.parent.parent / "lib"),
             "PYTHONPATH": str(PREFIX / "python-module-a100") + ":" + str(PREFIX / "python-overlay"),
             "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    return child


def main():
    stage, config, command = stage_command(sys.argv[1:])
    python = Path(json.loads(Path(config).read_text())["python"]["path"])
    if not python.is_absolute():
        raise ValueError("The installed Python interpreter must have an absolute path")
    child = child_environment(stage, config, python=python)
    executable = str(python)
    os.execve(executable, [executable, *command], child)


if __name__ == "__main__":
    main()
