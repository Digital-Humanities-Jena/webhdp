#!/usr/bin/env python3
"""Copy the reviewed COLMAP/ONNX dependency closure into a pinned flat directory.

Run on the allocated Linux GPU node. Only trusted, locally compiled ELF files
are inspected with ldd. The installed source prefixes are never changed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


HOST_LIBRARIES = re.compile(
    r"^(?:ld-linux.*|lib(?:c|m|pthread|dl|rt|resolv|util|anl|nss_[^.]+)\.so(?:\..*)?"
    r"|libpython.*|libcuda\.so(?:\..*)?|libnvidia-.*)$"
)


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--module", type=Path)
    parser.add_argument("--deps", type=Path, required=True)
    parser.add_argument("--cuda-site", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--pin-helper", type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get("SLURM_JOB_ID"), "Use the existing authorized allocation"
    install, deps, cuda = (path.resolve(strict=True) for path in (args.install, args.deps, args.cuda_site))
    destination = args.destination.resolve()
    assert not destination.exists(), "Use a new destination; retained closures are immutable"
    assert not any(destination.is_relative_to(path) for path in (install, deps, cuda))
    search = [install / name for name in ("thirdparty", "lib64", "lib")]
    search += [deps / "lib", deps / "targets/x86_64-linux/lib"]
    search += sorted(cuda.glob("*/lib"))
    search = [path for path in search if path.is_dir()]
    env = {**os.environ, "LD_LIBRARY_PATH": ":".join(map(str, search))}
    seeds = sorted(path for path in install.rglob("*.so*") if path.is_file())
    if args.module:
        seeds += sorted(args.module.resolve(strict=True).rglob("*.so"))
    # ONNX loads providers itself; cuDNN loads its component libraries itself.
    seeds += sorted((cuda / "cudnn/lib").glob("libcudnn*.so*"))
    assert any("providers_cuda" in path.name for path in seeds)
    assert any(path.name == "libcudnn.so.9" for path in seeds)
    files, inspected, excluded = {}, set(), {}

    def add(name, source):
        source = source.resolve(strict=True)
        if HOST_LIBRARIES.fullmatch(name):
            excluded[name] = str(source)
            return
        prior = files.get(name)
        if prior is not None:
            assert digest(prior) == digest(source), "Conflicting SONAME: " + name
        else:
            files[name] = source

    for seed in seeds:
        # The extension stays in its Python package; inspect its dependencies.
        if not args.module or not seed.is_relative_to(args.module.resolve()):
            add(seed.name, seed)
    queue = list(seeds)
    while queue:
        path = queue.pop().resolve(strict=True)
        if path in inspected:
            continue
        inspected.add(path)
        result = subprocess.run(["ldd", str(path)], env=env, text=True, capture_output=True, check=True)
        assert "not found" not in result.stdout, str(path) + "\n" + result.stdout
        for line in result.stdout.splitlines():
            match = re.match(r"\s*(\S+) => (/\S+) \(", line)
            if not match:
                continue
            name, source = match.groups()
            add(name, Path(source))
            if not HOST_LIBRARIES.fullmatch(name):
                queue.append(Path(source))

    # Discovery finishes before creating any published asset.
    temporary = destination.with_name(destination.name + ".in-progress")
    temporary.mkdir(parents=True, exist_ok=False)
    rows, identical = [], {}
    for name, source in sorted(files.items()):
        sha = digest(source)
        target = temporary / name
        if sha in identical:
            os.link(identical[sha], target)
        else:
            shutil.copy2(source, target)
            identical[sha] = target
        assert target.is_file() and not target.is_symlink() and digest(target) == sha
        rows.append({"name": name, "source": str(source), "sha256": sha, "bytes": target.stat().st_size})
    spec = importlib.util.spec_from_file_location("historic_pins", args.pin_helper)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    tree_sha = helper.tree_sha256(temporary)
    temporary.rename(destination)
    receipt = {"created_at": datetime.now(timezone.utc).isoformat(), "scope": "Native library closure only; no scientific inference claim",
               "slurm_job_id": os.environ["SLURM_JOB_ID"], "directory": str(destination), "sha256": tree_sha,
               "source_prefixes_modified": False, "ld_library_path_used": list(map(str, search)),
               "inspected_elf_count": len(inspected), "files": rows, "excluded_runtime_libraries": excluded}
    receipt_path = destination.with_name(destination.name + "-receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"libraries": len(rows), "sha256": tree_sha, "receipt": str(receipt_path)}), flush=True)


if __name__ == "__main__":
    main()
