#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/webhdp-user/webhdp}"
PID_DIR="$ROOT/run/pids-sing"
ENV_FILE="${ENV_FILE:-$ROOT/.env.hpc.singularity}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

BACKEND_PORT="${BACKEND_PORT:-5000}"
FAST_RENDERER_PORT="${FAST_RENDERER_PORT:-5002}"
ANY_TO_USDZ_PORT="${ANY_TO_USDZ_PORT:-5003}"
FRONTEND_IN_SINGULARITY="${FRONTEND_IN_SINGULARITY:-false}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
ENABLE_LOCAL_EDM_VALIDATION="${ENABLE_LOCAL_EDM_VALIDATION:-true}"
ENABLE_LOCAL_EDM_VALIDATOR_STACK="${ENABLE_LOCAL_EDM_VALIDATOR_STACK:-$ENABLE_LOCAL_EDM_VALIDATION}"
LOCAL_EDM_VALIDATOR_PORT="${LOCAL_EDM_VALIDATOR_PORT:-18080}"
LOCAL_EDM_XSLT_PORT="${LOCAL_EDM_XSLT_PORT:-18081}"

print_status() {
  local name="$1"
  local pid_file="$2"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" >/dev/null 2>&1; then
    echo "$name: running (pid $(cat "$pid_file"))"
  else
    echo "$name: stopped"
  fi
}

print_tcp_status() {
  local name="$1"
  local port="$2"
  if env -u LD_LIBRARY_PATH bash -c ":</dev/tcp/127.0.0.1/$port" >/dev/null 2>&1; then
    echo "$name: listening on 127.0.0.1:$port"
  else
    echo "$name: not listening on 127.0.0.1:$port"
  fi
}

print_status "redis" "$PID_DIR/redis.pid"
if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  print_status "local_edm_postgres" "$PID_DIR/local_edm_postgres.pid"
  print_status "local_edm_mongo" "$PID_DIR/local_edm_mongo.pid"
  print_status "local_edm_solr" "$PID_DIR/local_edm_solr.pid"
  print_status "local_edm_minio" "$PID_DIR/local_edm_minio.pid"
  print_status "local_edm_xslt" "$PID_DIR/local_edm_xslt.pid"
  print_status "local_edm_validator" "$PID_DIR/local_edm_validator.pid"
fi
print_status "fast_renderer" "$PID_DIR/fast_renderer.pid"
print_status "any_to_usdz" "$PID_DIR/any_to_usdz.pid"
print_status "backend" "$PID_DIR/backend.pid"
print_status "celery_worker" "$PID_DIR/celery_worker.pid"
if [[ "$FRONTEND_IN_SINGULARITY" == "true" ]]; then
  print_status "frontend" "$PID_DIR/frontend.pid"
fi

echo "--- listeners ---"
print_tcp_status "redis" "$REDIS_PORT"
print_tcp_status "backend" "$BACKEND_PORT"
print_tcp_status "fast_renderer" "$FAST_RENDERER_PORT"
print_tcp_status "any_to_usdz" "$ANY_TO_USDZ_PORT"
if [[ "$FRONTEND_IN_SINGULARITY" == "true" ]]; then
  print_tcp_status "frontend" "$FRONTEND_PORT"
fi
if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  print_tcp_status "local_edm_validator" "$LOCAL_EDM_VALIDATOR_PORT"
  print_tcp_status "local_edm_xslt" "$LOCAL_EDM_XSLT_PORT"
fi

echo "--- health ---"
for u in \
  $(if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then echo "http://127.0.0.1:${LOCAL_EDM_VALIDATOR_PORT}/actuator/health"; fi) \
  $(if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then echo "http://127.0.0.1:${LOCAL_EDM_XSLT_PORT}/default-edm-sorter.xsl"; fi) \
  "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" \
  "http://127.0.0.1:${FAST_RENDERER_PORT}/health" \
  "http://127.0.0.1:${ANY_TO_USDZ_PORT}/health"
do
  if curl -sf "$u" >/dev/null 2>&1; then
    echo "$u OK"
  else
    echo "$u FAIL"
  fi
done

if [[ "$FRONTEND_IN_SINGULARITY" == "true" ]]; then
  if curl -sf "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    echo "http://127.0.0.1:${FRONTEND_PORT}/ OK"
  else
    echo "http://127.0.0.1:${FRONTEND_PORT}/ FAIL"
  fi
fi
