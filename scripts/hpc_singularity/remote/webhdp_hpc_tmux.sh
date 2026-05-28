#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/webhdp-user/webhdp}"
SESSION="${WEBHDP_TMUX_SESSION:-webhdp-batch}"
CONFIG="${1:-${WEBHDP_BATCH_CONFIG:-}}"

if [[ -z "$CONFIG" ]]; then
  echo "Usage: $0 /path/to/webhdp_batch_config.json" >&2
  echo "Or set WEBHDP_BATCH_CONFIG." >&2
  exit 2
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not available on this host" >&2
  exit 1
fi

mkdir -p "$ROOT/logs" "$ROOT/run"
ORCH_LOG="${WEBHDP_TMUX_ORCHESTRATOR_LOG:-$ROOT/logs/webhdp-batch-orchestrator.log}"
BATCH="python3 scripts/hpc_singularity/remote/webhdp_hpc_batch.py"

cd "$ROOT"
if [[ "${WEBHDP_TMUX_SKIP_PREFLIGHT:-false}" != "true" ]]; then
  $BATCH preflight --config "$CONFIG" --fail
fi
if [[ "${WEBHDP_TMUX_PREPARE:-auto}" == "true" ]] || { [[ "${WEBHDP_TMUX_PREPARE:-auto}" == "auto" ]] && $BATCH summary --config "$CONFIG" | grep -q '"chunk_count": null'; }; then
  $BATCH prepare --config "$CONFIG"
fi

STATUS_CMD="cd '$ROOT' && watch -n 30 'scripts/hpc_singularity/remote/status_services.sh; echo; squeue -u \$USER -o \"%.18i %.12P %.28j %.10T %.10M %.10l %.20R\"'"
SUMMARY_CMD="cd '$ROOT' && watch -n 60 'python3 scripts/hpc_singularity/remote/webhdp_hpc_batch.py summary --config \"$CONFIG\" || true; echo; python3 scripts/hpc_singularity/remote/webhdp_hpc_batch.py diagnose --config \"$CONFIG\" | tail -n 80 || true'"
TAIL_CMD="tail -n 200 -F '$ORCH_LOG' '$ROOT'/logs/slurm-batch-*.out '$ROOT'/logs/slurm-batch-*.err 2>/dev/null"
ORCH_CMD="cd '$ROOT' && python3 scripts/hpc_singularity/remote/webhdp_hpc_batch.py resume --config '$CONFIG' 2>&1 | tee -a '$ORCH_LOG'"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach-session -t "$SESSION"
fi

tmux new-session -d -s "$SESSION" -n orchestrator "$ORCH_CMD"
tmux split-window -h -t "$SESSION:orchestrator" "$STATUS_CMD"
tmux split-window -v -t "$SESSION:orchestrator.1" "$SUMMARY_CMD"
tmux split-window -v -t "$SESSION:orchestrator.2" "$TAIL_CMD"
tmux select-layout -t "$SESSION:orchestrator" tiled
tmux attach-session -t "$SESSION"
