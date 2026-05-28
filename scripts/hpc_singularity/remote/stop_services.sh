#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/webhdp-user/webhdp}"
PID_DIR="$ROOT/run/pids-sing"
RUNTIME_DIR="$ROOT/run/runtime-sing"
ENV_FILE="${ENV_FILE:-$ROOT/.env.hpc.singularity}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

BACKEND_PORT="${BACKEND_PORT:-5000}"
FAST_RENDERER_PORT="${FAST_RENDERER_PORT:-5002}"
ANY_TO_USDZ_PORT="${ANY_TO_USDZ_PORT:-5003}"
REDIS_PORT="${REDIS_PORT:-6379}"
FRONTEND_IN_SINGULARITY="${FRONTEND_IN_SINGULARITY:-false}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
ENABLE_LOCAL_EDM_VALIDATION="${ENABLE_LOCAL_EDM_VALIDATION:-true}"
ENABLE_LOCAL_EDM_VALIDATOR_STACK="${ENABLE_LOCAL_EDM_VALIDATOR_STACK:-$ENABLE_LOCAL_EDM_VALIDATION}"
LOCAL_EDM_VALIDATOR_PORT="${LOCAL_EDM_VALIDATOR_PORT:-18080}"
LOCAL_EDM_XSLT_PORT="${LOCAL_EDM_XSLT_PORT:-18081}"
LOCAL_EDM_POSTGRES_PORT="${LOCAL_EDM_POSTGRES_PORT:-5432}"
LOCAL_EDM_MONGO_PORT="${LOCAL_EDM_MONGO_PORT:-27017}"
LOCAL_EDM_SOLR_PORT="${LOCAL_EDM_SOLR_PORT:-8983}"
LOCAL_EDM_MINIO_PORT="${LOCAL_EDM_MINIO_PORT:-9000}"

stop_pidfile() {
  local name="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "$name not running (no pid file)"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "Stopping $name (pid $pid)"
    kill "$pid" || true
    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" || true
    fi
  else
    echo "$name pid exists but process is not running"
  fi
  rm -f "$pid_file"
}

stop_port_listeners() {
  local name="$1"
  local port="$2"

  local pids
  pids="$(ss -ltnp "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)"
  if [[ -z "$pids" ]]; then
    echo "$name not listening on port $port"
    return 0
  fi

  echo "Stopping $name listeners on port $port: $pids"
  local pid
  for pid in $pids; do
    kill "$pid" >/dev/null 2>&1 || true
  done
  for _ in $(seq 1 20); do
    pids="$(ss -ltnp "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)"
    [[ -z "$pids" ]] && return 0
    sleep 1
  done
  for pid in $pids; do
    kill -9 "$pid" >/dev/null 2>&1 || true
  done
}

stop_pidfile "celery_worker" "$PID_DIR/celery_worker.pid"
stop_pidfile "frontend" "$PID_DIR/frontend.pid"
if [[ "$FRONTEND_IN_SINGULARITY" == "true" ]]; then
  stop_port_listeners "frontend" "$FRONTEND_PORT"
fi
stop_pidfile "backend" "$PID_DIR/backend.pid"
stop_pidfile "backend_gunicorn" "$RUNTIME_DIR/gunicorn-${BACKEND_PORT}.pid"
stop_port_listeners "backend" "$BACKEND_PORT"
stop_pidfile "any_to_usdz" "$PID_DIR/any_to_usdz.pid"
stop_port_listeners "any_to_usdz" "$ANY_TO_USDZ_PORT"
stop_pidfile "fast_renderer" "$PID_DIR/fast_renderer.pid"
stop_port_listeners "fast_renderer" "$FAST_RENDERER_PORT"
stop_pidfile "local_edm_validator" "$PID_DIR/local_edm_validator.pid"
if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  stop_port_listeners "local_edm_validator" "$LOCAL_EDM_VALIDATOR_PORT"
fi
stop_pidfile "local_edm_xslt" "$PID_DIR/local_edm_xslt.pid"
if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  stop_port_listeners "local_edm_xslt" "$LOCAL_EDM_XSLT_PORT"
fi
stop_pidfile "local_edm_minio_init" "$PID_DIR/local_edm_minio_init.pid"
stop_pidfile "local_edm_minio" "$PID_DIR/local_edm_minio.pid"
if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  stop_port_listeners "local_edm_minio" "$LOCAL_EDM_MINIO_PORT"
fi
stop_pidfile "local_edm_solr" "$PID_DIR/local_edm_solr.pid"
if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  stop_port_listeners "local_edm_solr" "$LOCAL_EDM_SOLR_PORT"
fi
stop_pidfile "local_edm_mongo" "$PID_DIR/local_edm_mongo.pid"
if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  stop_port_listeners "local_edm_mongo" "$LOCAL_EDM_MONGO_PORT"
fi
stop_pidfile "local_edm_postgres" "$PID_DIR/local_edm_postgres.pid"
if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  stop_port_listeners "local_edm_postgres" "$LOCAL_EDM_POSTGRES_PORT"
fi
stop_pidfile "hdp_server" "$PID_DIR/hdp_server.pid"
stop_pidfile "redis" "$PID_DIR/redis.pid"
stop_port_listeners "redis" "$REDIS_PORT"

echo "Services stopped"
