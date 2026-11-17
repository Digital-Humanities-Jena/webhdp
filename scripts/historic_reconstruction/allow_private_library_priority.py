#!/usr/bin/env python3
"""Convert a copied ELF64 interpreter RPATH to RUNPATH without changing its path.

The pinned native closure must precede the base interpreter's fallback libraries.
Only the owned sandbox copy is changed; source interpreter bytes are retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--interpreter", type=Path, required=True)
    parser.add_argument("--source-interpreter", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    root = args.rootfs.resolve(strict=True)
    target, source = (path.resolve(strict=True) for path in (args.interpreter, args.source_interpreter))
    assert target.is_relative_to(root) and not source.is_relative_to(root)
    assert (root.parent / "staging-owner.json").is_file()
    assert target.stat().st_nlink == 1 and not target.samefile(source), "Never edit a linked original"
    original, source_before = target.read_bytes(), source.read_bytes()
    assert original[:6] == b"\x7fELF\x02\x01", "Expected ELF64 little-endian"
    phoff = struct.unpack_from("<Q", original, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", original, 54)
    positions = []
    for index in range(phcount):
        start = phoff + index * phsize
        if struct.unpack_from("<I", original, start)[0] != 2:  # PT_DYNAMIC
            continue
        offset = struct.unpack_from("<Q", original, start + 8)[0]
        size = struct.unpack_from("<Q", original, start + 32)[0]
        for position in range(offset, offset + size, 16):
            tag = struct.unpack_from("<q", original, position)[0]
            assert tag != 29, "Already has RUNPATH; do not patch twice"
            if tag == 15:
                positions.append(position)
    assert len(positions) == 1, "Expected one DT_RPATH"
    changed = bytearray(original)
    struct.pack_into("<q", changed, positions[0], 29)  # DT_RUNPATH, same string-table offset
    assert sum(a != b for a, b in zip(original, changed)) == 1
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    backup = args.receipt.with_suffix(".original-interpreter")
    assert not backup.exists() and not args.receipt.exists()
    backup.write_bytes(original)
    target.write_bytes(changed)
    assert target.read_bytes() == changed and source.read_bytes() == source_before
    receipt = {"scope": "Copied sandbox interpreter loader metadata only", "target": str(target),
               "source_interpreter": str(source), "source_unchanged": True,
               "source_sha256": hashlib.sha256(source_before).hexdigest(),
               "original_sha256": hashlib.sha256(original).hexdigest(),
               "patched_sha256": hashlib.sha256(changed).hexdigest(),
               "dynamic_tag_offset": positions[0], "old_tag": "DT_RPATH", "new_tag": "DT_RUNPATH",
               "search_path_string_unchanged": True, "original_backup": str(backup)}
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
