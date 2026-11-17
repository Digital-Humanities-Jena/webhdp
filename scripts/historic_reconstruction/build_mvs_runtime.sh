#!/usr/bin/env bash
# Build a private MVS image without modifying its provisioned source environment.
# Use prepare, then copy/resync after dependency changes, then finalize only after
# a genuine scientific acceptance result succeeds. No allocation is submitted.
set -euo pipefail
umask 077
: "${SLURM_JOB_ID:?Run inside an existing authorized allocation}"
: "${HISTORIC_MVS_ROOT:?Private provisioned MVS runtime root required}"
: "${HISTORIC_BUILD_ROOT:?New isolated SIF build directory required}"
: "${HISTORIC_RUNNER_SOURCE:?Directory containing reviewed wrappers required}"
mode=${1:?Use prepare, copy or finalize}
case "$mode" in prepare|copy|finalize) ;; *) exit 2;; esac
[[ "$HISTORIC_MVS_ROOT" = /* && "$HISTORIC_BUILD_ROOT" = /* ]]
[[ -f "$HISTORIC_MVS_ROOT/operator-config.json" ]]
python3 - <<'PY'
import os
from pathlib import Path
target=Path(os.environ['HISTORIC_BUILD_ROOT']).resolve()
source=Path(os.environ['HISTORIC_MVS_ROOT']).resolve(strict=True)
assert not target.is_relative_to(source), 'Build root must be outside the source runtime'
if os.environ.get('HISTORIC_UBUNTU_ROOTFS'):
    base=Path(os.environ['HISTORIC_UBUNTU_ROOTFS']).resolve(strict=True)
    assert not target.is_relative_to(base), 'Build root must be outside the Ubuntu source sandbox'
PY
if [[ "$mode" = prepare ]]; then
    : "${HISTORIC_UBUNTU_ROOTFS:?Existing clean Ubuntu sandbox base required}"
    [[ ! -e "$HISTORIC_BUILD_ROOT" ]]
    [[ -f "$HISTORIC_UBUNTU_ROOTFS/etc/os-release" ]]
    mkdir -p "$HISTORIC_BUILD_ROOT/rootfs"
    # Reuse only the Ubuntu filesystem, excluding another runtime's scientific
    # environment, wrappers and environment customization.
    rsync -a --exclude='/work/***' --exclude='/app/***' \
        --exclude='/.singularity.d/env/95-historic.sh' \
        "$HISTORIC_UBUNTU_ROOTFS/" "$HISTORIC_BUILD_ROOT/rootfs/"
    cp "$HISTORIC_BUILD_ROOT/rootfs/etc/os-release" "$HISTORIC_BUILD_ROOT/base-os-release.txt"
fi
[[ -d "$HISTORIC_BUILD_ROOT/rootfs/.singularity.d" ]]
[[ ! -L "$HISTORIC_BUILD_ROOT/rootfs" ]]
if [[ "$mode" != prepare ]]; then
    [[ -f "$HISTORIC_BUILD_ROOT/prepare-receipt.json" ]]
fi
if [[ "$mode" != finalize ]]; then
python3 - "$mode" <<'PY'
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

mode = sys.argv[1]
source_root = Path(os.environ['HISTORIC_MVS_ROOT']).resolve(strict=True)
build = Path(os.environ['HISTORIC_BUILD_ROOT']).resolve(strict=True)
rootfs = build / 'rootfs'
config_path = source_root / 'operator-config.json'
config = json.loads(config_path.read_text())
environment = Path(config['python']['path']).parent.parent
assert environment.is_relative_to(source_root) and (environment / 'bin/python').is_file()
paths = [Path(config['source']['path'])]
paths += [Path(row['path']) for row in config.get('dependencies', [])]
paths += [Path(row['path']) for row in config.get('assets', {}).values()]
# Include provenance and licensing alongside the exact configured import roots.
paths += [path for pattern in ('*receipt.json', '*install*.log', 'pip-*.log', 'pip-freeze.txt',
                              'conda-build.log', 'dependencies.log', 'download.log', 'precache.log',
                              'extension-build*.log', 'precompile_mvs_extension.sh',
                              'source/LICENSE*', 'source/NOTICE*', 'source/COPYING*', 'source/README*')
          for path in source_root.glob(pattern) if path.is_file()]
paths += [config_path]
for path in paths:
    assert path.is_absolute() and path.is_relative_to(source_root) and path.exists(), path
paths = sorted(set(paths), key=lambda path: len(path.parts))
roots = []
for path in paths:
    if not any(path.is_relative_to(parent) for parent in roots if parent.is_dir()):
        roots.append(path)

def destination(path):
    result = rootfs / str(path).lstrip('/')
    assert result.resolve().is_relative_to(rootfs.resolve())
    return result

def sync(path):
    target = destination(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        target.mkdir(exist_ok=True)
        command = ['rsync', '-a', '--delete', str(path) + '/', str(target) + '/']
    else:
        command = ['rsync', '-a', str(path), str(target)]
    subprocess.run(command, check=True)

for path in roots:
    sync(path)

if mode == 'copy':
    target = destination(environment)
    site = Path('lib/python3.10/site-packages')
    (target / site).mkdir(parents=True, exist_ok=True)
    tasks = [(['rsync', '-a', '--exclude=/' + site.as_posix() + '/***',
               str(environment) + '/', str(target) + '/'])]
    tasks += [['rsync', '-a', str(path), str(target / site) + '/']
              for path in sorted((environment / site).iterdir())]
    def copy(command):
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(copy, tasks))
    # Reconcile removals and directory metadata inside this owned copy only.
    sync(environment)
    verification = subprocess.run(['rsync', '-ani', '--delete', str(environment) + '/', str(target) + '/'],
                                  check=True, capture_output=True, text=True)
    if verification.stdout.strip():
        raise RuntimeError('Source environment changed during copying; rerun copy after dependency freeze')
    (rootfs / 'app').mkdir(exist_ok=True)
    wrapper_source = Path(os.environ['HISTORIC_RUNNER_SOURCE'])
    for name in ('component_runner.py', 'upstream.py'):
        shutil.copy2(wrapper_source / name, rootfs / 'app' / name)
    (rootfs / '.singularity.d/env/95-historic.sh').write_text(
        f'export PATH="{environment}/bin:$PATH"\n'
        f'export HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG="{config_path}"\n'
        'export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1\n'
        'export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1\n')
receipt = {'phase': mode, 'completed_at': datetime.now(timezone.utc).isoformat(),
           'source_root': str(source_root), 'rootfs': str(rootfs),
           'configured_roots_copied': list(map(str, roots)),
           'environment_copied': mode == 'copy', 'source_environment_modified': False,
           'copy_verification': 'rsync archive quick-check, including removals' if mode == 'copy' else None}
(build / (mode + '-receipt.json')).write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt), flush=True)
PY
    exit 0
fi

: "${HISTORIC_MVS_ACCEPTANCE_RESULT:?Successful real MVS result is required before image finalization}"
python3 - "$HISTORIC_MVS_ACCEPTANCE_RESULT" "$HISTORIC_BUILD_ROOT/copy-receipt.json" "$HISTORIC_MVS_ROOT/operator-config.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
result=json.load(open(sys.argv[1])); receipt=json.load(open(sys.argv[2])); config=json.load(open(sys.argv[3]))
assert result.get('success') is True and result.get('artifacts'), 'MVS scientific acceptance has not passed'
assert result.get('summary', {}).get('stage') == 'mvs' and result['summary'].get('upstream_execution') is True
assert receipt['environment_copied'] is True
for artifact in result['artifacts']:
    path=Path(artifact['path']); digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    assert digest.hexdigest() == artifact['metadata']['sha256'] and path.stat().st_size == artifact['metadata']['bytes']
report=json.load(open(result['outputs']['report']))
assert report['metrics']['stage'] == 'mvs' and report['metrics']['upstream_execution'] is True
assert report['source_sha256'] == config['source']['sha256']
assert report['runtime_pins']['python_sha256'] == config['python']['sha256']
assert report['runtime_pins']['dependencies'] == [item['sha256'] for item in config.get('dependencies', [])]
assert report['runtime_pins']['assets'] == {key: item['sha256'] for key,item in config.get('assets', {}).items()}
PY
environment=$(python3 -c 'import json,pathlib,sys; print(pathlib.Path(json.load(open(sys.argv[1]))["python"]["path"]).parent.parent)' "$HISTORIC_MVS_ROOT/operator-config.json")
rootfs="$HISTORIC_BUILD_ROOT/rootfs"
cmp "$HISTORIC_MVS_ROOT/operator-config.json" "$rootfs$HISTORIC_MVS_ROOT/operator-config.json"
for wrapper in component_runner.py upstream.py; do
    cmp "$HISTORIC_RUNNER_SOURCE/$wrapper" "$rootfs/app/$wrapper"
done
rsync -ani --delete "$environment/" "$rootfs$environment/" > "$HISTORIC_BUILD_ROOT/final-environment-drift.txt"
if [[ -s "$HISTORIC_BUILD_ROOT/final-environment-drift.txt" ]]; then
    echo 'Environment changed after copying; rerun copy after dependency freeze.' >&2
    exit 1
fi
# Only the copied image is normalized; original environments remain untouched.
chmod -R a+rX "$rootfs"
singularity exec --cleanenv --containall --no-home "$rootfs" "$environment/bin/python" -c \
    'import sys,torch,pycolmap,numpy,PIL,trimesh,yaml; assert sys.version_info[:2]==(3,10); print(sys.version,torch.__version__,pycolmap.__version__)'
singularity exec --cleanenv --containall --no-home "$rootfs" "$environment/bin/python" -c \
    'import sys; sys.path.insert(0,"/app"); import upstream; upstream.load_config("mvs"); print("Pinned MVS configuration verified")'
python3 - "$rootfs/app" "$HISTORIC_BUILD_ROOT/runtime-source-sha256.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
pins={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(sys.argv[1]).glob('*.py')}
Path(sys.argv[2]).write_text(json.dumps(pins,indent=2)+'\n')
PY
# Singularity 3.11 has no --mksquashfs-args. Build the partition explicitly with
# bounded CPU/memory, then assemble it using the supported SIF object commands.
[[ ! -e "$HISTORIC_BUILD_ROOT/historic-mvs.sif" ]]
"${HISTORIC_MKSQUASHFS:-/usr/sbin/mksquashfs}" "$rootfs" "$HISTORIC_BUILD_ROOT/historic-mvs.squashfs" \
    -noappend -all-root -processors 2 -mem 1G -comp gzip -Xcompression-level 1 -no-progress
singularity sif new "$HISTORIC_BUILD_ROOT/historic-mvs.sif"
singularity sif add --datatype 4 --partarch 2 --partfs 1 --parttype 2 --groupid 1 \
    "$HISTORIC_BUILD_ROOT/historic-mvs.sif" "$HISTORIC_BUILD_ROOT/historic-mvs.squashfs"
singularity sif add --datatype 6 --groupid 1 "$HISTORIC_BUILD_ROOT/historic-mvs.sif" \
    "$HISTORIC_BUILD_ROOT/runtime-source-sha256.json"
sha256sum "$HISTORIC_BUILD_ROOT/historic-mvs.sif" > "$HISTORIC_BUILD_ROOT/historic-mvs.sif.sha256"
# Verify the actual immutable SIF before registering it. This imports the real
# fuser/CUDA extension and validates the writable per-run cache without neural
# inference. The existing allocation exposes CUDA; thread caps keep this probe
# at two CPUs regardless of the environment's general four-CPU default.
probe=$(mktemp -d "$HISTORIC_BUILD_ROOT/sif-preflight.XXXXXXXX")
cat > "$probe/check.py" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, '/app')
import upstream
output=Path('/verification/output')
output.mkdir()
config=upstream.load_config('mvs')
env=upstream._environment(config, output)
assert int(env['OMP_NUM_THREADS']) <= 2
upstream._preflight('mvs', config, env, output, {'batch_size': 1, 'fusion_max_depth': 30.0, 'fusion_resolution': 0.04})
upstream._assert_runtime_unchanged(config)
result={'success': True, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'Actual SIF MVS imports, CUDA availability, writable JIT cache, unchanged pinned runtime',
        'neural_inference_executed': False, 'cpu_thread_limit': int(env['OMP_NUM_THREADS']),
        'source_sha256': config['source']['sha256'], 'config_sha256': config['_config_sha256']}
(output/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
PY
singularity exec --nv --cleanenv --containall --no-home --bind "$probe:/verification" \
    "$HISTORIC_BUILD_ROOT/historic-mvs.sif" env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
    "$environment/bin/python" /verification/check.py > "$probe/console.log" 2>&1
cp "$probe/output/verification.json" "$HISTORIC_BUILD_ROOT/sif-verification.json"
printf '%s\n' "$probe" > "$HISTORIC_BUILD_ROOT/sif-verification-directory.txt"
