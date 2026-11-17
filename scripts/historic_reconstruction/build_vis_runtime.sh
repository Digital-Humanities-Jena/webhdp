#!/bin/bash
# Package a private copy of the already provisioned Draco scientific environment.
# Run inside an existing allocation. Never modifies the source environments.
set -euo pipefail
umask 077
: "${SLURM_JOB_ID:?An existing allocation is required}"
: "${HISTORIC_BUILD_ROOT:?New isolated build directory required}"
: "${HISTORIC_ENV_PREFIX:?Self-contained conda Python/COLMAP environment required}"
: "${HISTORIC_PYCOLMAP_SITE:?Source site-packages containing CUDA pycolmap required}"
: "${HISTORIC_RUNNER_SOURCE:?Directory containing reviewed component_runner.py required}"
[[ "$HISTORIC_BUILD_ROOT" = /* && ! -e "$HISTORIC_BUILD_ROOT" ]]
[[ -x "$HISTORIC_ENV_PREFIX/bin/python" && -x "$HISTORIC_ENV_PREFIX/bin/colmap" ]]
[[ -d "$HISTORIC_PYCOLMAP_SITE/pycolmap" && -f "$HISTORIC_RUNNER_SOURCE/component_runner.py" ]]
mkdir -p "$HISTORIC_BUILD_ROOT"
cd "$HISTORIC_BUILD_ROOT"
export SINGULARITY_CACHEDIR="$PWD/cache"
export SINGULARITY_TMPDIR="$PWD/tmp"
mkdir -p "$SINGULARITY_CACHEDIR" "$SINGULARITY_TMPDIR"
printf '%s\n' "$(date -u +%FT%TZ) pulling Ubuntu base"
singularity build --sandbox rootfs docker://ubuntu:22.04
printf '%s\n' "$(date -u +%FT%TZ) copying scientific environment"
# Preserve its internal prefix to avoid changing conda library/search paths.
mkdir -p "rootfs$(dirname "$HISTORIC_ENV_PREFIX")"
cp -a "$HISTORIC_ENV_PREFIX" "rootfs$HISTORIC_ENV_PREFIX"
site="rootfs$HISTORIC_ENV_PREFIX/lib/python3.12/site-packages"
python3 - "$site" <<'PY'
from pathlib import Path
import shutil,sys
site = Path(sys.argv[1])
assert site.resolve().is_relative_to(Path('rootfs').resolve())
for item in site.glob('pycolmap*'):
    if item.is_symlink() or item.is_file():
        item.unlink()
    else:
        shutil.rmtree(item)
PY
for package in "$HISTORIC_PYCOLMAP_SITE"/pycolmap*; do
    cp -a "$package" "$site/"
done
mkdir -p rootfs/app
cp "$HISTORIC_RUNNER_SOURCE/component_runner.py" "$HISTORIC_RUNNER_SOURCE/upstream.py" rootfs/app/
cat > rootfs/.singularity.d/env/95-historic.sh <<EOF
export PATH="$HISTORIC_ENV_PREFIX/bin:\$PATH"
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export QT_QPA_PLATFORM=offscreen
EOF
# The enclosing build directory remains private. Inside a root-owned SIF,
# unprivileged execution must be able to traverse/read the copied payload.
# This changes only the new rootfs, never the source scientific environment.
chmod -R a+rX rootfs
python3 - <<'PY'
from pathlib import Path
import hashlib,json
pins = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('rootfs/app').glob('*.py')}
Path('runtime-source-sha256.json').write_text(json.dumps(pins, indent=2) + '\n')
PY
printf '%s\n' "$(date -u +%FT%TZ) checking isolated sandbox imports"
singularity exec --cleanenv --containall --no-home --nv rootfs "$HISTORIC_ENV_PREFIX/bin/python" -c \
 'import sys,pycolmap,numpy,PIL,trimesh,yaml; assert pycolmap.has_cuda; print(sys.version); print("pycolmap",pycolmap.__version__,"CUDA",pycolmap.has_cuda)'
singularity exec --cleanenv --containall --no-home --nv rootfs "$HISTORIC_ENV_PREFIX/bin/colmap" -h > colmap-version.txt
printf '%s\n' "$(date -u +%FT%TZ) compressing immutable SIF"
# Singularity 3.11 has no --mksquashfs-args. Its supported SIF object commands
# allow explicit CPU/memory-limited compression without global config changes.
mksquashfs rootfs historic-portable-cuda.squashfs -noappend -all-root \
    -processors 2 -mem 1G -comp gzip -Xcompression-level 1 -no-progress
singularity sif new historic-portable-cuda.sif
singularity sif add --datatype 4 --partarch 2 --partfs 1 --parttype 2 --groupid 1 \
    historic-portable-cuda.sif historic-portable-cuda.squashfs
singularity sif add --datatype 6 --groupid 1 historic-portable-cuda.sif runtime-source-sha256.json
sha256sum historic-portable-cuda.sif > historic-portable-cuda.sif.sha256
singularity exec --cleanenv --containall --no-home --nv historic-portable-cuda.sif python -c \
 'import pycolmap; assert pycolmap.has_cuda; print("pinned SIF CUDA",pycolmap.__version__)'
printf '%s\n' "$(date -u +%FT%TZ) private validation SIF ready"
