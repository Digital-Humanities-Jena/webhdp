#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

"$ROOT_DIR/scripts/hpc_singularity/build_export_archives.sh"
"$ROOT_DIR/scripts/hpc_singularity/transfer_archives.sh"
"$ROOT_DIR/scripts/hpc_singularity/install_sif_on_hpc.sh"
"$ROOT_DIR/scripts/hpc_singularity/sync_remote_scripts.sh"

echo "Done. Next steps:"
echo "1) Copy and edit env on HPC:"
echo "   ssh hpc-login 'cp /home/webhdp-user/webhdp/scripts/hpc_singularity/remote/env.hpc.singularity.example /home/webhdp-user/webhdp/.env.hpc.singularity'"
echo "2) Submit Slurm job:"
echo "   ssh hpc-login 'cd /home/webhdp-user/webhdp && sbatch scripts/hpc_singularity/remote/webhdp.sbatch'"
