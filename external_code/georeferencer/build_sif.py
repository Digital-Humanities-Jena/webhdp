#!/usr/bin/env python3
"""Build a self-contained Linux HPC image from checksum-verified inputs."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

UPSTREAM_REVISION = 'e50e4562b43c0b105d77e417d01fedb5139529a6'


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-image', required=True, type=Path)
    parser.add_argument('--base-sha256', required=True)
    parser.add_argument('--weights', required=True, type=Path)
    parser.add_argument('--weights-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--scratch', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists; use a new candidate filename.')
    for path, checksum in ((args.base_image, args.base_sha256), (args.weights, args.weights_sha256)):
        if len(checksum) != 64 or digest(path) != checksum.lower():
            raise SystemExit(f'Checksum verification failed for {path.name}.')
    runtime = shutil.which('singularity') or shutil.which('apptainer')
    if not runtime:
        raise SystemExit('Singularity or Apptainer is required.')
    with tempfile.TemporaryDirectory(prefix='georef-build-', dir=args.scratch) as temporary:
        root = Path(temporary)
        upstream = root / 'upstream'
        subprocess.run(['git', 'clone', 'https://github.com/3DOM-FBK/3DGeoRef.git', str(upstream)], check=True)
        subprocess.run(['git', '-C', str(upstream), 'checkout', '--detach', UPSTREAM_REVISION], check=True)
        sandbox = root / 'rootfs'
        subprocess.run([runtime, 'build', '--tmpdir', str(root), '--sandbox', str(sandbox), str(args.base_image.resolve())], check=True)
        for name in ('pipeline', 'hdri'):
            shutil.copytree(upstream / name, sandbox / 'app' / name, dirs_exist_ok=True)
        component = sandbox / 'opt/webhdp/georeferencer'
        component.mkdir(parents=True, exist_ok=True)
        # The upstream floating pip install can select CUDA 13 builds. Package
        # a CUDA 12.1 runtime for driver compatibility independently of that base.
        python_runtime = sandbox / 'opt/webhdp/python'
        reuse_runtime = (python_runtime / 'torch').is_dir()
        python_runtime.mkdir(parents=True, exist_ok=True)
        if reuse_runtime:
            subprocess.run([runtime, 'exec', '--cleanenv', str(sandbox), 'env', 'PYTHONPATH=/opt/webhdp/python',
                'python3', '-c', 'import torch; assert torch.__version__ == "2.5.1+cu121"'], check=True)
        else:
            subprocess.run([runtime, 'exec', '--cleanenv', '--writable', str(sandbox), 'python3', '-m', 'pip', '--isolated',
                'install', '--cert', '/etc/ssl/certs/ca-certificates.crt', '--no-cache-dir', '--ignore-installed', '--target', '/opt/webhdp/python',
                '--report', '/opt/webhdp/georeferencer/python-packages.json',
                '--index-url', 'https://download.pytorch.org/whl/cu121', 'torch==2.5.1+cu121'], check=True)
        # Keep torchvision import-compatible even though the reference workflow
        # itself only uses torch. Do not leave the base image's CUDA 13 version
        # visible alongside the compatible torch runtime.
        subprocess.run([runtime, 'exec', '--cleanenv', '--writable', str(sandbox), 'python3', '-m', 'pip', '--isolated',
            'install', '--cert', '/etc/ssl/certs/ca-certificates.crt', '--no-cache-dir', '--upgrade', '--no-deps',
            '--target', '/opt/webhdp/python', '--report', '/opt/webhdp/georeferencer/vision-package.json',
            '--index-url', 'https://download.pytorch.org/whl/cu121', 'torchvision==0.20.1+cu121'], check=True)
        # This image implements the reference workflow. Remove duplicate GPU
        # stacks and the unused DIM checkout from the upstream base so users do
        # not have to transfer CUDA 13 libraries alongside the selected runtime.
        for packages in sandbox.glob('usr/local/lib/python3.*/dist-packages'):
            for name in ('torch', 'torchvision', 'torchaudio', 'triton', 'nvidia'):
                for path in [packages/name, *packages.glob(name+'-*.dist-info')]:
                    if path.is_symlink():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
            for path in packages.glob('nvidia_*.dist-info'):
                shutil.rmtree(path)
        if (sandbox/'workspace/dim').is_dir():
            shutil.rmtree(sandbox/'workspace/dim')
        source = Path(__file__).resolve().parent
        for name in ('runner.py', 'geometry.py', 'blender_entry.py', 'UPSTREAM_LICENSE'):
            shutil.copy2(source / name, component / name)
        shutil.copy2(source.parent / 'mesh_optimizer/runner.py', component / 'glb_contract.py')
        shutil.copy2(args.weights, component / 'outdoor_ds.ckpt')
        (component / 'provenance.json').write_text(json.dumps({
            'upstream_revision': UPSTREAM_REVISION, 'base_image_sha256': args.base_sha256.lower(),
            'weights_sha256': args.weights_sha256.lower(),
            'files': {path.name: digest(path) for path in component.iterdir()
                      if path.is_file() and path.name != 'provenance.json'}}, indent=2))
        for path in (python_runtime, *python_runtime.rglob('*')):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        for path in (component.parent, *component.rglob('*'), component,
                     sandbox/'app/pipeline', * (sandbox/'app/pipeline').rglob('*'),
                     sandbox/'app/hdri', *(sandbox/'app/hdri').rglob('*')):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() else 0o644)
        subprocess.run([runtime, 'exec', str(sandbox), 'env', 'PYTHONPATH=/opt/webhdp/python', 'python3', '-c',
            'import cv2, numpy, rasterio, pyproj, torch; from kornia.feature import LoFTR; '
            'm=LoFTR(pretrained=None); m.load_state_dict(torch.load("/opt/webhdp/georeferencer/outdoor_ds.ckpt", map_location="cpu", weights_only=True)["state_dict"])'], check=True)
        subprocess.run([runtime, 'build', '--tmpdir', str(root), str(args.output.resolve()), str(sandbox)], check=True)
    checksum = digest(args.output)
    args.output.with_suffix('.sif.sha256').write_text(f'{checksum}  {args.output.name}\n')
    print(f'Built {args.output.name}: SHA-256 {checksum}')


if __name__ == '__main__':
    main()
