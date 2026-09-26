#!/usr/bin/env python3
"""Build the immutable component on Linux from verified runtime inputs."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

UPSTREAM_REVISION = 'a1e76f43b9257be5288ad18c52b640c6a3f4829a'
CHECKPOINT_SHA256 = '463efc8a3afd3913142aa025e0125c00f16ef452b8de6a132ebe32bbe7877ee4'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def make_runtime_readable(root):
    for path in [root, *root.rglob('*')]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-image', required=True, type=Path)
    parser.add_argument('--base-sha256', required=True, help='Trusted SHA-256 of the upstream runtime SIF')
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--scratch', type=Path, help='Build filesystem with at least 40 GB free')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists. Use a new filename; installed images must not be overwritten.')
    if digest(args.base_image) != args.base_sha256.lower():
        raise SystemExit('Base image checksum does not match.')
    if digest(args.checkpoint) != CHECKPOINT_SHA256:
        raise SystemExit('Checkpoint checksum does not match.')
    runtime = shutil.which('singularity') or shutil.which('apptainer')
    if not runtime:
        raise SystemExit('Singularity or Apptainer is required.')
    with tempfile.TemporaryDirectory(prefix='mesh-optimizer-build-', dir=args.scratch) as scratch:
        root = Path(scratch)
        source = root / 'upstream'
        subprocess.run(['git', 'clone', 'https://github.com/3DOM-FBK/mesh-optimizer.git', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'checkout', '--detach', UPSTREAM_REVISION], check=True)
        sandbox = root / 'rootfs'
        subprocess.run([runtime, 'build', '--tmpdir', str(root), '--sandbox', str(sandbox), str(args.base_image.resolve())], check=True)
        for name in ('pipeline', 'config'):
            shutil.copytree(source / name, sandbox / 'app' / name, dirs_exist_ok=True)
        shutil.copy2(args.checkpoint, sandbox / 'app/model_objaverse.ckpt')
        component = sandbox / 'opt/webhdp/mesh_optimizer'
        component.mkdir(parents=True)
        for name in ('runner.py', 'blender_entry.py'):
            shutil.copy2(Path(__file__).parent / name, component / name)
        shutil.copy2(source / 'LICENSE', component / 'UPSTREAM_LICENSE')
        (component / 'provenance.json').write_text(json.dumps({
            'upstream_revision': UPSTREAM_REVISION, 'base_image_sha256': args.base_sha256.lower(),
            'checkpoint_sha256': CHECKPOINT_SHA256}, indent=2))
        # SquashFS assigns root ownership. Local umasks and copied private modes
        # must not make the packaged application unreadable to HPC users.
        for directory in (component.parent, component):
            directory.chmod(0o755)
        for tree in (component, sandbox / 'app/pipeline', sandbox / 'app/config'):
            make_runtime_readable(tree)
        (sandbox / 'app/model_objaverse.ckpt').chmod(0o644)
        subprocess.run([runtime, 'build', '--tmpdir', str(root), str(args.output.resolve()), str(sandbox)], check=True)
    checksum = digest(args.output)
    args.output.with_suffix('.sif.sha256').write_text(f'{checksum}  {args.output.name}\n')
    print(f'Built {args.output.name}: SHA-256 {checksum}')


if __name__ == '__main__':
    main()
