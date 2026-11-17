#!/usr/bin/env python3
"""Atomically copy reviewed launch/config files into an inactive linked snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
from revise_learned_cuda_runtime import atomic_copy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--configuration-directory", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--runtime-directory", type=Path)
    args = parser.parse_args()
    root = args.rootfs.resolve(strict=True)
    assert (root.parent / "staging-owner.json").is_file()
    copies = [(args.launcher, root / "opt/historic-learned/learned_entrypoint.py")]
    for stage in ("original_sfm", "geolocalization", "dense_intrinsics"):
        name = stage + "-operator-config.json"
        copies.append((args.configuration_directory / name, root / "opt/historic-learned" / name))
    if args.runtime_directory:
        for name in ("component_runner.py", "upstream.py"):
            for relative in ("app", "opt/historic-learned/runtime"):
                copies.append((args.runtime_directory / name, root / relative / name))
    results = []
    for source, target in copies:
        assert source.is_file() and not source.resolve().is_relative_to(root)
        source_bytes = source.read_bytes()
        atomic_copy(source, target)
        assert source.read_bytes() == target.read_bytes() == source_bytes
        results.append({"path": str(target.relative_to(root)), "sha256": hashlib.sha256(source_bytes).hexdigest()})
    print(json.dumps({"rootfs": str(root), "atomic_replacements": results, "shared_inodes_modified": False}))


if __name__ == "__main__":
    main()
