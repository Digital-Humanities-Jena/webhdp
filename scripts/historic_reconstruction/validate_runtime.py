#!/usr/bin/env python3
"""Run genuine image-to-geometry acceptance checks in an isolated workspace.

The inputs must be overlapping photographs. No retained reconstruction is used.
Use the runtime's scientific Python, and run --gpu/--dense only on an allocation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def artifact(response: dict, name: str, output_dir: Path) -> Path:
    value = response['outputs'][name]
    if isinstance(value, dict):
        value = value.get('path') or value.get('file_path') or value.get('value')
    path = Path(value)
    if not path.is_absolute():
        path = output_dir / path
    path = path.resolve()
    if not path.is_relative_to(output_dir.resolve()) or not path.is_file():
        raise ValueError(f'Output artifact {name} must exist inside its stage directory')
    return path


def check_ply_geometry(path: Path) -> dict:
    """Decode exported geometry independently, including finite coordinates and indices."""
    scalar_types = {'char': 'b', 'uchar': 'B', 'short': 'h', 'ushort': 'H',
                    'int': 'i', 'uint': 'I', 'float': 'f', 'double': 'd',
                    'int8': 'b', 'uint8': 'B', 'int16': 'h', 'uint16': 'H',
                    'int32': 'i', 'uint32': 'I', 'float32': 'f', 'float64': 'd'}
    with path.open('rb') as stream:
        if stream.readline().strip() != b'ply':
            raise ValueError('Invalid PLY signature')
        elements, encoding = [], None
        for _ in range(200):
            fields = stream.readline().decode('ascii').split()
            if not fields:
                raise ValueError('Invalid PLY header')
            if fields[0] == 'format':
                encoding = fields[1]
            elif fields[0] == 'element':
                elements.append((fields[1], int(fields[2]), []))
            elif fields[0] == 'property':
                elements[-1][2].append(fields[1:])
            elif fields[0] == 'end_header':
                break
        else:
            raise ValueError('Unterminated PLY header')
        if encoding not in {'ascii', 'binary_little_endian', 'binary_big_endian'}:
            raise ValueError('Unsupported PLY format')
        counts = {name: count for name, count, _ in elements}
        vertices = counts.get('vertex', 0)
        if not 0 < vertices <= 100_000_000:
            raise ValueError('Invalid PLY vertex count')
        endian = '>' if encoding == 'binary_big_endian' else '<'
        for name, count, properties in elements:
            for _ in range(count):
                tokens = iter(stream.readline().decode('ascii').split()) if encoding == 'ascii' else None

                def number(kind, tokens=tokens):
                    code = scalar_types[kind]
                    if tokens is not None:
                        raw = next(tokens)
                        return float(raw) if code in {'f', 'd'} else int(raw)
                    size = struct.calcsize(code)
                    raw = stream.read(size)
                    if len(raw) != size:
                        raise ValueError('Truncated PLY geometry')
                    return struct.unpack(endian + code, raw)[0]

                record = {}
                for prop in properties:
                    if prop[0] == 'list':
                        length = number(prop[1])
                        if not 0 <= length <= 1024:
                            raise ValueError('Invalid PLY list length')
                        record[prop[3]] = [number(prop[2]) for _ in range(length)]
                    else:
                        record[prop[1]] = number(prop[0])
                if name == 'vertex' and any(not math.isfinite(record[axis]) for axis in ('x', 'y', 'z')):
                    raise ValueError('PLY contains non-finite coordinates')
                if name == 'face':
                    indexes = record.get('vertex_indices', record.get('vertex_index', []))
                    if len(indexes) < 3 or any(type(index) is not int or not 0 <= index < vertices for index in indexes):
                        raise ValueError('PLY contains invalid face indexes')
        return counts


def run(args: argparse.Namespace) -> dict:
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    if args.gpu and not os.environ.get('SLURM_JOB_ID'):
        raise ValueError('--gpu requires an active Slurm allocation')
    if args.dense and not args.gpu:
        raise ValueError('--dense requires --gpu')
    import pycolmap
    from PIL import Image
    if args.gpu and not pycolmap.has_cuda:
        raise ValueError('The pycolmap build does not support CUDA')
    photos = sorted(p for p in args.input_dir.iterdir()
                    if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.tif', '.tiff'})
    if len(photos) < 3:
        raise ValueError('At least three overlapping photographs are required')
    proof = {'started_at': datetime.now(UTC).isoformat(),
             'slurm_job_id': os.environ.get('SLURM_JOB_ID'), 'gpu_requested': args.gpu,
             'pycolmap_version': pycolmap.__version__, 'pycolmap_has_cuda': pycolmap.has_cuda,
             'source_count': len(photos), 'source_sha256': {p.name: sha256(p) for p in photos},
             'runtime_sha256': sha256(args.runtime_dir / 'component_runner.py'),
             'stages': {}, 'success': False}
    proof_path = root / 'acceptance.json'

    def save():
        proof_path.write_text(json.dumps(proof, indent=2) + '\n')

    def stage(name, inputs, parameters):
        out = root / name
        out.mkdir()
        request = out / 'request.json'
        response = out / 'result.json'
        request.write_text(json.dumps({'inputs': inputs, 'parameters': parameters}) + '\n')
        first_input = next(iter(inputs.values()))
        first_path = first_input[0] if isinstance(first_input, list) else first_input
        env = dict(os.environ, WEBHDP_COMPONENT_REQUEST=str(request),
                   WEBHDP_COMPONENT_RESPONSE=str(response), WEBHDP_OUTPUT_DIR=str(out),
                   WEBHDP_INPUT_DIR=str(Path(first_path).resolve().parent),
                   OMP_NUM_THREADS=os.environ.get('SLURM_CPUS_PER_TASK', '4'),
                   OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        start = time.monotonic()
        with (out / 'process.log').open('w') as log:
            proc = subprocess.run([sys.executable, str(args.runtime_dir / 'component_runner.py'), name,
                                   '--webhdp-input', str(request), '--webhdp-output-dir', str(out),
                                   '--webhdp-result', str(response)], env=env,
                                  stdout=log, stderr=subprocess.STDOUT, timeout=5400, check=False)
        proof['stages'][name] = {'exit_code': proc.returncode,
                                'duration_seconds': round(time.monotonic() - start, 3)}
        save()
        if proc.returncode:
            raise RuntimeError(f'{name} failed; inspect {out / "process.log"}')
        result = json.loads(response.read_text())
        if result.get('status') not in (None, 'success', 'succeeded', 'completed') or result.get('success') is False:
            raise RuntimeError(f'{name} returned a failure response')
        return result, out

    save()
    try:
        prepared, prepare_dir = stage('prepare', {'input_files': [str(p.resolve()) for p in photos]},
                                      {'max_image_size': 960, 'jpeg_quality': 95})
        dataset = artifact(prepared, 'dataset', prepare_dir)
        with zipfile.ZipFile(dataset) as package:
            names = [n for n in package.namelist() if n.startswith('images/') and n.lower().endswith('.jpg')]
            if len(names) != len(photos):
                raise ValueError('Image preparation lost photographs')
            for name in names:
                with package.open(name) as file, Image.open(file) as image:
                    if max(image.size) > 960 or image.getexif():
                        raise ValueError('Image preparation did not normalize dimensions and EXIF')
        paired, pairs_dir = stage('pairs', {'input_file': str(dataset)}, {'method': 'exhaustive'})
        pair_dataset = artifact(paired, 'dataset', pairs_dir)
        pair_lines = artifact(paired, 'pairs', pairs_dir).read_text().strip().splitlines()
        if len(pair_lines) != len(photos) * (len(photos) - 1) // 2:
            raise ValueError('Exhaustive pair count is incorrect')
        sparse, sparse_dir = stage('sparse', {'input_file': str(pair_dataset)},
                                   {'use_gpu': args.gpu, 'max_num_features': 8192,
                                    'min_model_size': 3, 'camera_model': 'SIMPLE_RADIAL'})
        reconstruction = artifact(sparse, 'reconstruction', sparse_dir)
        extracted = root / 'independent-sparse-check'
        extracted.mkdir()
        with zipfile.ZipFile(reconstruction) as package:
            for member in package.infolist():
                destination = (extracted / member.filename).resolve()
                if not destination.is_relative_to(extracted):
                    raise ValueError('Unsafe output archive path')
            package.extractall(extracted)
        candidates = list(extracted.rglob('cameras.bin'))
        if len(candidates) != 1:
            raise ValueError('Expected exactly one COLMAP model')
        model = pycolmap.Reconstruction(str(candidates[0].parent))
        registered, points = model.num_reg_images(), model.num_points3D()
        errors = [float(point.error) for point in model.points3D.values()]
        if registered < max(3, len(photos) // 2) or points < 100:
            raise ValueError('Sparse reconstruction has insufficient registered geometry')
        if any(not math.isfinite(error) for error in errors) or sum(errors) / len(errors) >= 5:
            raise ValueError('Sparse reconstruction errors are invalid or exceed five pixels')
        cloud = artifact(sparse, 'point_cloud', sparse_dir)
        if check_ply_geometry(cloud).get('vertex') != points:
            raise ValueError('Sparse point export does not match the COLMAP model')
        proof['sparse'] = {'registered_images': registered, 'points3d': points,
                           'mean_reprojection_error_pixels': sum(errors) / len(errors),
                           'reconstruction_sha256': sha256(reconstruction)}
        save()
        if args.dense:
            dense, dense_dir = stage('dense', {'input_file': str(reconstruction)},
                                      {'max_image_size': 960, 'geometric_consistency': True})
            dense_cloud = artifact(dense, 'point_cloud', dense_dir)
            mesh = artifact(dense, 'mesh', dense_dir)
            dense_count = check_ply_geometry(dense_cloud).get('vertex', 0)
            mesh_counts = check_ply_geometry(mesh)
            if dense_count < 1000 or mesh_counts.get('vertex', 0) < 100 or mesh_counts.get('face', 0) < 100:
                raise ValueError('Dense reconstruction produced insufficient geometry')
            proof['dense'] = {'points': dense_count, 'mesh_vertices': mesh_counts['vertex'],
                              'mesh_faces': mesh_counts['face'], 'mesh_sha256': sha256(mesh)}
        if sha256(args.runtime_dir / 'component_runner.py') != proof['runtime_sha256']:
            raise ValueError('Runtime source changed during acceptance')
        proof['success'] = True
        proof['finished_at'] = datetime.now(UTC).isoformat()
        save()
        return proof
    except Exception as exc:
        proof['error'] = str(exc)
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--gpu', action='store_true')
    parser.add_argument('--dense', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == '__main__':
    main()
