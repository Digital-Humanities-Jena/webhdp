#!/usr/bin/env python3
"""Make a separate linked sandbox and atomically pin its compatible CUDA runtime.

The successful earlier sandbox and the shared ART environment remain unchanged.
Future writes to linked snapshot files must also use copy-and-rename semantics.
"""
from datetime import datetime, timezone
import argparse
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=target.name + ".copy-", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-build", type=Path, required=True)
    parser.add_argument("--new-build", type=Path, required=True)
    parser.add_argument("--base-libraries", type=Path, required=True)
    parser.add_argument("--new-libraries", type=Path, required=True)
    parser.add_argument("--cuda-runtime", type=Path, required=True)
    parser.add_argument("--runtime-relative-path", type=Path, required=True,
                        help="CUDA library location relative to the rootfs")
    parser.add_argument("--pin-helper", type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get("SLURM_JOB_ID")
    base = args.base_build.resolve(strict=True)
    new = args.new_build.resolve()
    source_cuda = args.cuda_runtime.resolve(strict=True)
    assert (base / "staging-owner.json").is_file()
    assert not new.is_relative_to(base) and not base.is_relative_to(new)
    spec = importlib.util.spec_from_file_location("pins", args.pin_helper)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    base_library_sha = helper.tree_sha256(args.base_libraries)
    torch_relative = args.runtime_relative_path
    if torch_relative.is_absolute() or ".." in torch_relative.parts or torch_relative.name != "libcudart.so.12":
        parser.error("--runtime-relative-path must identify libcudart.so.12 inside the rootfs")
    closure_relative = Path("opt/historic-learned/runtime-libraries-a100/libcudart.so.12")
    before = {str(path): sha(base / "rootfs" / path) for path in (torch_relative, closure_relative)}
    desired_sha = sha(source_cuda)
    if new.exists():
        assert json.loads((new / "staging-owner.json").read_text())["base"] == str(base / "rootfs")
        assert not (new / "cuda-revision.json").exists(), "Retain completed snapshots"
    else:
        new.mkdir(parents=True)
        (new / "staging-owner.json").write_text(json.dumps({"base": str(base / "rootfs"),
            "purpose": "private CUDA12.9 learned runtime revision; original snapshot retained"}) + "\n")
        # Kernel protected-hardlink rules can reject root-owned base files. Fill
        # only those missing files with ordinary copies in the following step.
        subprocess.run(["cp", "-al", str(base / "rootfs"), str(new / "rootfs")], check=False)
    subprocess.run(["rsync", "-a", "--ignore-existing", str(base / "rootfs") + "/", str(new / "rootfs") + "/"], check=True)
    args.new_libraries.mkdir(exist_ok=True)
    expected_names = {path.name for path in args.base_libraries.iterdir()}
    assert {path.name for path in args.new_libraries.iterdir()} <= expected_names
    for source in args.base_libraries.iterdir():
        target = args.new_libraries / source.name
        assert source.is_file() and not source.is_symlink()
        if target.exists():
            assert not target.is_symlink()
            assert target.samefile(source) or sha(target) == sha(source) or (source.name == "libcudart.so.12" and sha(target) == desired_sha)
        else:
            try:
                os.link(source, target)
            except OSError as exc:
                if exc.errno not in {errno.EPERM, errno.EXDEV, errno.EOPNOTSUPP}:
                    raise
                atomic_copy(source, target)
    atomic_copy(source_cuda, args.new_libraries / "libcudart.so.12")
    for relative in (torch_relative, closure_relative):
        target = new / "rootfs" / relative
        assert not target.is_symlink()
        atomic_copy(source_cuda, target)
        assert sha(target) == desired_sha and target.stat().st_nlink == 1
    assert before == {str(path): sha(base / "rootfs" / path) for path in (torch_relative, closure_relative)}
    assert helper.tree_sha256(args.base_libraries) == base_library_sha
    assert sha(source_cuda) == desired_sha
    result = {"completed_at": datetime.now(timezone.utc).isoformat(), "scope": "Private CUDA runtime snapshot revision; inference verification follows",
              "base_build": str(base), "new_build": str(new), "original_runtime_files_unchanged": before,
              "source_cuda_runtime": str(source_cuda), "cuda_runtime_sha256": desired_sha,
              "new_library_directory": str(args.new_libraries), "new_library_sha256": helper.tree_sha256(args.new_libraries),
              "source_environments_modified": False, "changed_paths": list(before),
              "snapshot_copy_strategy": "Hardlink where permitted; ordinary-copy fallback otherwise",
              "mutation_policy": "Atomic replacement only; never chmod/chown or in-place write linked files"}
    (new / "cuda-revision.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
