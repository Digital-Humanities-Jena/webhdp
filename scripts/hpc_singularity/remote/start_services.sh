#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/webhdp-user/webhdp}"
SIF_DIR="${SIF_DIR:-$ROOT/images/sif}"
ENV_FILE="${ENV_FILE:-$ROOT/.env.hpc.singularity}"

LOG_DIR="$ROOT/logs-sing"
PID_DIR="$ROOT/run/pids-sing"
RUNTIME_DIR="$ROOT/run/runtime-sing"
DB_PATH="${DB_PATH:-$ROOT/instance/hdp_web.db}"

mkdir -p "$LOG_DIR" "$PID_DIR" "$RUNTIME_DIR" \
  "$ROOT/instance" \
  "$ROOT/databases" \
  "$ROOT/hdp-shared/sessions" \
  "$ROOT/data/local_input" \
  "$ROOT/data/local_output" \
  "$ROOT/images/docker-archive" \
  "$ROOT/images/sif"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

HOST_HTTP_PROXY="${HTTP_PROXY:-}"
HOST_HTTPS_PROXY="${HTTPS_PROXY:-}"
HOST_FTP_PROXY="${FTP_PROXY:-}"
HOST_http_proxy="${http_proxy:-}"
HOST_https_proxy="${https_proxy:-}"
HOST_ftp_proxy="${ftp_proxy:-}"
HOST_NO_PROXY="${NO_PROXY:-}"
HOST_no_proxy="${no_proxy:-}"

# Load port/config overrides for host-side orchestration.
set -a
source "$ENV_FILE"
set +a

if [[ "${NO_PROXY:-}" == "*" && -n "$HOST_NO_PROXY" ]]; then
  export NO_PROXY="$HOST_NO_PROXY"
fi
if [[ "${no_proxy:-}" == "*" && -n "$HOST_no_proxy" ]]; then
  export no_proxy="$HOST_no_proxy"
fi

export HTTP_PROXY="${HTTP_PROXY:-$HOST_HTTP_PROXY}"
export HTTPS_PROXY="${HTTPS_PROXY:-$HOST_HTTPS_PROXY}"
export FTP_PROXY="${FTP_PROXY:-$HOST_FTP_PROXY}"
export http_proxy="${http_proxy:-$HOST_http_proxy}"
export https_proxy="${https_proxy:-$HOST_https_proxy}"
export ftp_proxy="${ftp_proxy:-$HOST_ftp_proxy}"
export NO_PROXY="${NO_PROXY:-$HOST_NO_PROXY}"
export no_proxy="${no_proxy:-$HOST_no_proxy}"

proxy_env_opts=()
for proxy_var in \
  HTTP_PROXY HTTPS_PROXY FTP_PROXY http_proxy https_proxy ftp_proxy NO_PROXY no_proxy; do
  proxy_value="${!proxy_var:-}"
  if [[ -n "$proxy_value" ]]; then
    proxy_env_opts+=(--env "$proxy_var=$proxy_value")
  fi
done

BACKEND_PORT="${BACKEND_PORT:-5000}"
FAST_RENDERER_PORT="${FAST_RENDERER_PORT:-5002}"
ANY_TO_USDZ_PORT="${ANY_TO_USDZ_PORT:-5003}"
REDIS_PORT="${REDIS_PORT:-6379}"
FRONTEND_IN_SINGULARITY="${FRONTEND_IN_SINGULARITY:-false}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
ENABLE_LOCAL_EDM_VALIDATION="${ENABLE_LOCAL_EDM_VALIDATION:-true}"
ENABLE_LOCAL_EDM_VALIDATOR_STACK="${ENABLE_LOCAL_EDM_VALIDATOR_STACK:-$ENABLE_LOCAL_EDM_VALIDATION}"
LOCAL_EDM_VALIDATOR_REQUIRED="${LOCAL_EDM_VALIDATOR_REQUIRED:-$ENABLE_LOCAL_EDM_VALIDATION}"
LOCAL_EDM_VALIDATOR_PORT="${LOCAL_EDM_VALIDATOR_PORT:-18080}"
LOCAL_EDM_POSTGRES_PORT="${LOCAL_EDM_POSTGRES_PORT:-5432}"
LOCAL_EDM_MONGO_PORT="${LOCAL_EDM_MONGO_PORT:-27017}"
LOCAL_EDM_SOLR_PORT="${LOCAL_EDM_SOLR_PORT:-8983}"
LOCAL_EDM_SOLR_ZK_PORT="${LOCAL_EDM_SOLR_ZK_PORT:-9983}"
LOCAL_EDM_MINIO_PORT="${LOCAL_EDM_MINIO_PORT:-9000}"
LOCAL_EDM_MINIO_CONSOLE_PORT="${LOCAL_EDM_MINIO_CONSOLE_PORT:-9001}"
LOCAL_EDM_XSLT_PORT="${LOCAL_EDM_XSLT_PORT:-18081}"
LOCAL_EDM_VALIDATOR_URL="${LOCAL_EDM_VALIDATOR_URL:-http://127.0.0.1:$LOCAL_EDM_VALIDATOR_PORT}"
LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR="${LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR:-false}"
LOCAL_EDM_FFMPEG_BIN_DIR="${LOCAL_EDM_FFMPEG_BIN_DIR:-$ROOT/tools/ffmpeg-8/bin}"
LOCAL_EDM_VALIDATOR_APP_JAR="${LOCAL_EDM_VALIDATOR_APP_JAR:-$ROOT/tools/local-edm-validator/app.jar}"
local_edm_sorter_url="http://127.0.0.1:$LOCAL_EDM_XSLT_PORT/default-edm-sorter.xsl"
local_edm_transformation_url="http://127.0.0.1:$LOCAL_EDM_XSLT_PORT/default_transformation.xslt"
LOCAL_EDM_XSLT_URL="${LOCAL_EDM_XSLT_URL:-$local_edm_sorter_url}"
LOCAL_EDM_TRANSFORMATION_URL="${LOCAL_EDM_TRANSFORMATION_URL:-$local_edm_transformation_url}"
LOAD_CUDA_ENV="${LOAD_CUDA_ENV:-true}"
REQUIRE_GPU="${REQUIRE_GPU:-true}"
ENABLE_RENDERER_NV="${ENABLE_RENDERER_NV:-true}"
CUDA_VISIBLE_DEVICES_VALUE="${CUDA_VISIBLE_DEVICES:-}"
SLURM_GPUS_ON_NODE_VALUE="${SLURM_GPUS_ON_NODE:-}"
SLURM_STEP_GPUS_VALUE="${SLURM_STEP_GPUS:-}"
SLURM_JOB_GPUS_VALUE="${SLURM_JOB_GPUS:-}"
NVIDIA_VISIBLE_DEVICES_VALUE="${NVIDIA_VISIBLE_DEVICES:-${CUDA_VISIBLE_DEVICES_VALUE:-all}}"

app_env_opts=(
  --env "ENABLE_LOCAL_EDM_VALIDATION=$ENABLE_LOCAL_EDM_VALIDATION"
  --env "LOCAL_EDM_VALIDATOR_REQUIRED=$LOCAL_EDM_VALIDATOR_REQUIRED"
  --env "LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=$LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR"
  --env "LOCAL_EDM_VALIDATOR_URL=$LOCAL_EDM_VALIDATOR_URL"
)

required_sifs=(backend.sif fast-renderer.sif any-to-usdz.sif redis.sif)

if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  required_sifs+=(
    local-edm-postgres.sif
    local-edm-mongo.sif
    local-edm-solr.sif
    local-edm-minio.sif
    local-edm-mc.sif
    local-edm-validator.sif
  )
fi

for sif in "${required_sifs[@]}"; do
  if [[ ! -f "$SIF_DIR/$sif" ]]; then
    echo "Missing image: $SIF_DIR/$sif" >&2
    exit 1
  fi
done

if [[ "$FRONTEND_IN_SINGULARITY" == "true" ]] && [[ ! -f "$SIF_DIR/frontend.sif" ]]; then
  echo "FRONTEND_IN_SINGULARITY=true but missing image: $SIF_DIR/frontend.sif" >&2
  exit 1
fi

# Critical on this HPC: use local /tmp for Singularity cache/tmp.
export TMPDIR="/tmp"
export SINGULARITY_TMPDIR="/tmp"
export SINGULARITY_CACHEDIR="/tmp/${USER}-sing-cache"
mkdir -p "$SINGULARITY_CACHEDIR"

# Load site CUDA environment (if available), then verify GPU visibility.
if [[ "$LOAD_CUDA_ENV" == "true" ]]; then
  if bash -ic "type set_cuda121 >/dev/null 2>&1"; then
    echo "Validating CUDA environment via set_cuda121 (isolated shell)"
    if ! bash -ic "set_cuda121 && nvidia-smi >/dev/null 2>&1"; then
      echo "Warning: set_cuda121 validation failed; continuing with current CUDA environment" >&2
    fi
  else
    echo "CUDA alias set_cuda121 not found; continuing with current environment"
  fi
fi

if [[ "$REQUIRE_GPU" == "true" ]]; then
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi not found on PATH; GPU/CUDA environment is not ready" >&2
    exit 1
  fi
  if ! env -u LD_LIBRARY_PATH nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi failed; GPU/CUDA environment is not ready" >&2
    exit 1
  fi
  echo "nvidia-smi (host):"
  env -u LD_LIBRARY_PATH nvidia-smi || true
fi

renderer_exec_opts=()
if [[ "$ENABLE_RENDERER_NV" == "true" ]]; then
  renderer_exec_opts+=(--nv)
fi

common_backend_binds=(
  "-B" "$ROOT/instance:/app/instance"
  "-B" "$ROOT/logs:/app/logs"
  "-B" "$RUNTIME_DIR:/runtime"
  "-B" "$ROOT/hdp-shared/sessions:/shared/sessions"
  "-B" "$ROOT/data/local_input:/data/local_input"
  "-B" "$ROOT/data/local_output:/data/local_output"
  "-B" "$ROOT/api_utils.py:/app/api_utils.py"
  "-B" "$ROOT/app.py:/app/app.py"
  "-B" "$ROOT/celery_app.py:/app/celery_app.py"
  "-B" "$ROOT/config.py:/app/config.py"
  "-B" "$ROOT/constants.py:/app/constants.py"
  "-B" "$ROOT/database:/app/database"
  "-B" "$ROOT/docs:/app/docs"
  "-B" "$ROOT/exceptions.py:/app/exceptions.py"
  "-B" "$ROOT/middleware.py:/app/middleware.py"
  "-B" "$ROOT/routes:/app/routes"
  "-B" "$ROOT/schema_xsds:/app/schema_xsds"
  "-B" "$ROOT/schemas:/app/schemas"
  "-B" "$ROOT/security.py:/app/security.py"
  "-B" "$ROOT/services:/app/services"
  "-B" "$ROOT/session_manager.py:/app/session_manager.py"
  "-B" "$ROOT/tasks.py:/app/tasks.py"
  "-B" "$ROOT/validation.py:/app/validation.py"
  "-B" "$ROOT/workflow_status.py:/app/workflow_status.py"
  "-B" "$ROOT/external_code:/app/external_code"
)

if [[ -d "/work" ]]; then
  common_backend_binds+=("-B" "/work:/work")
fi

for optional_root_file in \
  iiifmanifest_template.json \
  kpbc_rcin_lod_mapping.json \
  test_model.glb \
  zenodo_metadata_schema.json; do
  if [[ -f "$ROOT/$optional_root_file" ]]; then
    common_backend_binds+=("-B" "$ROOT/$optional_root_file:/app/$optional_root_file:ro")
  fi
done

if [[ -f "$ROOT/credentials/google-credentials.json" ]]; then
  common_backend_binds+=("-B" "$ROOT/credentials/google-credentials.json:/app/credentials/google-credentials.json:ro")
fi

common_worker_binds=("${common_backend_binds[@]}")

common_renderer_binds=(
  "-B" "$ROOT/hdp-shared/sessions:/shared/sessions"
  "-B" "$ROOT/data/local_input:/data/local_input"
  "-B" "$ROOT/data/local_output:/data/local_output"
  "-B" "$ROOT/external_code:/app/external_code"
)

if [[ -d "/work" ]]; then
  common_renderer_binds+=("-B" "/work:/work")
fi

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" >/dev/null 2>&1
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local delay="${4:-2}"

  for _ in $(seq 1 "$attempts"); do
    if env -u LD_LIBRARY_PATH curl -sf "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  echo "$name did not become healthy at $url" >&2
  return 1
}

edm_resource_matches() {
  local file="$1" checksum="$2" actual_checksum
  [[ -f "$file" ]] || return 1
  actual_checksum="$(sha256sum <"$file")" || return 1
  [[ "${actual_checksum%% *}" == "$checksum" ]]
}

download_edm_resource() {
  local url="$1" destination="$2" checksum="$3" temp_path

  if edm_resource_matches "$destination" "$checksum"; then
    return 0
  fi

  temp_path="$(mktemp "${destination}.XXXXXX")" || return 1
  if env -u LD_LIBRARY_PATH curl -fsSL --retry 2 --connect-timeout 10 --max-time 60 "$url" -o "$temp_path" &&
    edm_resource_matches "$temp_path" "$checksum" &&
    mv -f "$temp_path" "$destination"; then
    return 0
  fi

  rm -f "$temp_path"
  echo "Could not fetch or verify EDM resource at $url" >&2
  return 1
}

wait_for_port() {
  local name="$1"
  local host="$2"
  local port="$3"
  local attempts="${4:-60}"
  local delay="${5:-2}"

  for _ in $(seq 1 "$attempts"); do
    if env -u LD_LIBRARY_PATH bash -c ":</dev/tcp/$host/$port" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  echo "$name did not open $host:$port" >&2
  return 1
}

start_with_pidfile() {
  local name="$1"
  local pid_file="$2"
  shift 2

  if is_running "$pid_file"; then
    echo "$name already running (pid $(cat "$pid_file"))"
    return 0
  fi

  echo "Starting $name..."
  nohup "$@" >>"$LOG_DIR/$name.log" 2>&1 &
  echo $! >"$pid_file"
  sleep 1
  if ! is_running "$pid_file"; then
    echo "Failed to start $name" >&2
    return 1
  fi
}

service_health_ok() {
  local frontend_ok=true
  if [[ "$FRONTEND_IN_SINGULARITY" == "true" ]]; then
    env -u LD_LIBRARY_PATH curl -sf "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null 2>&1 || frontend_ok=false
  fi

  env -u LD_LIBRARY_PATH bash -c ":</dev/tcp/127.0.0.1/$REDIS_PORT" >/dev/null 2>&1 && \
    pgrep -u "$USER" -f "celery -A celery_app.celery worker.*--concurrency=${CELERY_WORKER_CONCURRENCY:-2}" >/dev/null 2>&1 && \
    env -u LD_LIBRARY_PATH curl -sf "http://127.0.0.1:$BACKEND_PORT/api/v1/health" >/dev/null 2>&1 && \
    { [[ "$LOCAL_EDM_VALIDATOR_REQUIRED" != "true" ]] || env -u LD_LIBRARY_PATH curl -sf "$LOCAL_EDM_VALIDATOR_URL/actuator/health" >/dev/null 2>&1; } && \
    env -u LD_LIBRARY_PATH curl -sf "http://127.0.0.1:$FAST_RENDERER_PORT/health" >/dev/null 2>&1 && \
    env -u LD_LIBRARY_PATH curl -sf "http://127.0.0.1:$ANY_TO_USDZ_PORT/health" >/dev/null 2>&1 && \
    [[ "$frontend_ok" == "true" ]]
}

watch_services_forever() {
  local interval="${WEBHDP_SERVICE_WATCHDOG_INTERVAL_SECONDS:-300}"
  echo "All services healthy. Keeping job alive with watchdog interval ${interval}s..."
  while true; do
    sleep "$interval"
    if ! service_health_ok; then
      echo "Service watchdog detected an unhealthy process or endpoint at $(date -Iseconds)" >&2
      "$ROOT/scripts/hpc_singularity/remote/status_services.sh" || true
      exit 1
    fi
    echo "Service watchdog OK at $(date -Iseconds)"
  done
}

REDIS_PID_FILE="$PID_DIR/redis.pid"
if is_running "$REDIS_PID_FILE"; then
  echo "redis already running (pid $(cat "$REDIS_PID_FILE"))"
else
  start_with_pidfile "redis" "$REDIS_PID_FILE" \
    singularity exec --cleanenv --env-file "$ENV_FILE" "${proxy_env_opts[@]}" \
      -B "$RUNTIME_DIR:/runtime" \
      "$SIF_DIR/redis.sif" \
      redis-server --bind 127.0.0.1 --port "$REDIS_PORT" --dir /runtime --dbfilename redis.rdb
fi

if [[ "$ENABLE_LOCAL_EDM_VALIDATOR_STACK" == "true" ]]; then
  echo "Starting local EDM validator stack..."
  mkdir -p \
    "$ROOT/local-edm/postgres" \
    "$ROOT/local-edm/postgres-run" \
    "$ROOT/local-edm/mongo" \
    "$ROOT/local-edm/solr-home" \
    "$ROOT/local-edm/solr-logs" \
    "$ROOT/local-edm/minio" \
    "$ROOT/local-edm/config" \
    "$ROOT/local-edm/xslt" \
    "$ROOT/local-edm/tmp"

  if [[ "$LOCAL_EDM_XSLT_URL" == "$local_edm_sorter_url" ]]; then
    download_edm_resource "http://ftp.eanadev.org/schema_zips/edm_sorter-20260630.xsl" \
      "$ROOT/local-edm/xslt/default-edm-sorter.xsl" \
      "421d1b942a06979f20ff338cb55944d86ab35f3bca6e711e20dcdf91ad4851a1"
  fi
  if [[ "$LOCAL_EDM_TRANSFORMATION_URL" == "$local_edm_transformation_url" ]]; then
    download_edm_resource "https://raw.githubusercontent.com/europeana/metis-framework/6bc36a5c692eda22542fbc3f552e1b9e3c1b4eae/metis-transformation/metis-transformation-service/src/main/resources/default_transformation.xslt" \
      "$ROOT/local-edm/xslt/default_transformation.xslt" \
      "fa6e1ac795777b3c190c65088d752aa8eb721da778f69d86ee67f686f4016f1b"
  fi

  cat >"$ROOT/local-edm/config/application.yml" <<EOF
info:
  app:
    title: Local EDM Validator
    description: Local EDM validation and METIS Sandbox operations for WebHDP
    version: 1.0.0-local-hpc
    edm-schema-version: "20260720"
    contact:
      name: WebHDP Local EDM Validator
      email: noreply@webhdp.local
      url: http://localhost:${LOCAL_EDM_VALIDATOR_PORT}
management:
  endpoints:
    web:
      exposure:
        include: ["health", "info", "loggers", "metrics", "scheduledtasks", "beans"]
    access:
      default: read_only
  endpoint:
    health:
      access: read_only
      show-details: always
    info:
      access: read_only
  info:
    env:
      enabled: true
truststore:
  path:
  password:
elastic:
  apm:
    enabled: false
spring:
  application:
    name: Metis Sandbox Local
  servlet:
    multipart:
      max-file-size: 64MB
      max-request-size: 64MB
  security:
    oauth2:
      resourceserver:
        jwt:
          jwk-set-uri: http://localhost:7080/realms/europeana/protocol/openid-connect/certs
  datasource:
    jdbcUrl: jdbc:postgresql://127.0.0.1:${LOCAL_EDM_POSTGRES_PORT}/metis-sandbox
    driverClassName: org.postgresql.Driver
    username: local
    password: local
  batch:
    job:
      enabled: false
    jdbc:
      initialize-schema: always
  sql:
    init:
      mode: always
  jpa:
    open-in-view: false
    generate-ddl: true
    hibernate:
      ddl-auto: update
sandbox:
  batch-job-executor:
    job-state-poll-interval-millis: 100
  workflow:
    HARVEST_OAI: { chunkSize: 5, parallelizeSize: 1 }
    HARVEST_FILE: { chunkSize: 5, parallelizeSize: 1 }
    VALIDATE: { chunkSize: 5, parallelizeSize: 1 }
    TRANSFORM: { chunkSize: 5, parallelizeSize: 1 }
    NORMALIZE: { chunkSize: 5, parallelizeSize: 1 }
    ENRICH: { chunkSize: 5, parallelizeSize: 1 }
    MEDIA: { chunkSize: 5, parallelizeSize: 1 }
    INDEX: { chunkSize: 5, parallelizeSize: 1 }
    DEBIAS: { chunkSize: 5, parallelizeSize: 1 }
  cors:
    mapping: "*"
  rate-limit:
    enabled: false
    bandwidth: { capacity: 1000000, time: 3600 }
  debias:
    url: http://localhost:8081/metis-debias
    connectTimeout: 300
    requestTimeout: 300
  dataset:
    clean:
      frequency: 0 0 0 * * ?
      days-to-preserve: 7
    max-size: 1000
  metrics:
    frequency: "*/30 * * * * *"
  validation:
    direct:
      enabled: true
    edm-sorter-url: ${LOCAL_EDM_XSLT_URL}
    executor:
      pool-size: 10
    predefinedSchemas:
      EDM-INTERNAL:
        url: http://ftp.eanadev.org/schema_zips/europeana_schemas-20260720.zip
        rootLocation: EDM-INTERNAL.xsd
        schematronLocation: schematron/schematron-internal.xsl
      EDM-EXTERNAL:
        url: http://ftp.eanadev.org/schema_zips/europeana_schemas-20260720.zip
        rootLocation: EDM.xsd
        schematronLocation: schematron/schematron.xsl
  transformation:
    xslt-url: ${LOCAL_EDM_TRANSFORMATION_URL}
    xslt-update-frequency: 0 0 * * * *
  enrichment:
    enabled: false
    dereference-url: http://localhost:8082
    enrichment-properties:
      entity-management-url: http://localhost:8082/entity
      entity-api-url: http://localhost:8082/entity
      entity-api-token-endpoint: http://localhost:8082/token
      entity-api-grant-params: client_id=local-edm-validator&client_secret=&grant_type=client_credentials
  publish:
    mongo:
      application-name: metis-sandbox-local
      db: metis-sandbox
      hosts: 127.0.0.1
      ports: ${LOCAL_EDM_MONGO_PORT}
      authentication-db: admin
      username: local
      password: local
      ssl-enable: false
      max-connection-pool-size: 10
    solr:
      hosts: http://127.0.0.1:${LOCAL_EDM_SOLR_PORT}/solr/metis_sandbox_publish_local
      zookeeper:
        hosts: 127.0.0.1
        ports: ${LOCAL_EDM_SOLR_ZK_PORT}
        default:
          collection: metis_sandbox_publish_local
        timeout: 10
  s3:
    access-key: local
    secret-key: localpassword
    endpoint: http://127.0.0.1:${LOCAL_EDM_MINIO_PORT}
    signing-region: eu-west-2
    thumbnails-bucket: metis-sandbox-bucket
  portal:
    publish:
      dataset-base-url: http://localhost:${LOCAL_EDM_VALIDATOR_PORT}/
      record-base-url: http://localhost:${LOCAL_EDM_VALIDATOR_PORT}/item
EOF

  start_with_pidfile "local_edm_postgres" "$PID_DIR/local_edm_postgres.pid" \
    singularity exec --cleanenv --env POSTGRES_DB=metis-sandbox \
      --env POSTGRES_USER=local --env POSTGRES_PASSWORD=local \
      --env PGDATA=/var/lib/postgresql/data/pgdata \
      -B "$ROOT/local-edm/postgres:/var/lib/postgresql/data" \
      -B "$ROOT/local-edm/postgres-run:/var/run/postgresql" \
      "$SIF_DIR/local-edm-postgres.sif" \
      docker-entrypoint.sh postgres -p "$LOCAL_EDM_POSTGRES_PORT"
  wait_for_port "local_edm_postgres" 127.0.0.1 "$LOCAL_EDM_POSTGRES_PORT" 60 2

  start_with_pidfile "local_edm_mongo" "$PID_DIR/local_edm_mongo.pid" \
    singularity exec --cleanenv --env MONGO_INITDB_DATABASE=metis-sandbox \
      --env MONGO_INITDB_ROOT_USERNAME=local --env MONGO_INITDB_ROOT_PASSWORD=local \
      -B "$ROOT/local-edm/mongo:/data/db" \
      "$SIF_DIR/local-edm-mongo.sif" \
      docker-entrypoint.sh mongod --bind_ip 127.0.0.1 --port "$LOCAL_EDM_MONGO_PORT"
  wait_for_port "local_edm_mongo" 127.0.0.1 "$LOCAL_EDM_MONGO_PORT" 60 2

  if [[ ! -f "$ROOT/local-edm/solr-home/solr.xml" ]]; then
    echo "Preparing writable Solr home..."
    singularity exec --cleanenv \
      -B "$ROOT/local-edm/solr-home:/solr-home" \
      "$SIF_DIR/local-edm-solr.sif" \
      sh -c "cp -R /opt/solr/server/solr/. /solr-home/"
  fi

  start_with_pidfile "local_edm_solr" "$PID_DIR/local_edm_solr.pid" \
    singularity exec --cleanenv --writable-tmpfs \
      -B "$ROOT/local-edm/solr-home:/opt/solr/server/solr" \
      -B "$ROOT/local-edm/solr-logs:/opt/solr/server/logs" \
      "$SIF_DIR/local-edm-solr.sif" \
      docker-entrypoint.sh solr start -c -f -p "$LOCAL_EDM_SOLR_PORT"
  wait_for_http "local_edm_solr" "http://127.0.0.1:${LOCAL_EDM_SOLR_PORT}/solr/admin/collections?action=LIST" 90 2

  start_with_pidfile "local_edm_minio" "$PID_DIR/local_edm_minio.pid" \
    singularity exec --cleanenv --env MINIO_ROOT_USER=local --env MINIO_ROOT_PASSWORD=localpassword \
      -B "$ROOT/local-edm/minio:/data" \
      "$SIF_DIR/local-edm-minio.sif" \
      minio server /data --address "127.0.0.1:${LOCAL_EDM_MINIO_PORT}" --console-address "127.0.0.1:${LOCAL_EDM_MINIO_CONSOLE_PORT}"
  wait_for_http "local_edm_minio" "http://127.0.0.1:${LOCAL_EDM_MINIO_PORT}/minio/health/ready" 60 2

  start_with_pidfile "local_edm_minio_init" "$PID_DIR/local_edm_minio_init.pid" \
    singularity exec --cleanenv "$SIF_DIR/local-edm-mc.sif" \
      sh -c "mc alias set local http://127.0.0.1:${LOCAL_EDM_MINIO_PORT} local localpassword && mc mb --ignore-existing local/metis-sandbox-bucket && sleep infinity"

  start_with_pidfile "local_edm_xslt" "$PID_DIR/local_edm_xslt.pid" \
    python3 -m http.server "$LOCAL_EDM_XSLT_PORT" --bind 127.0.0.1 --directory "$ROOT/local-edm/xslt"
  wait_for_http "local_edm_sorter" "$LOCAL_EDM_XSLT_URL" 30 1
  wait_for_http "local_edm_transformation" "$LOCAL_EDM_TRANSFORMATION_URL" 30 1

  local_edm_validator_binds=(
    -B "$ROOT/local-edm/config:/config:ro"
    -B "$ROOT/local-edm/tmp:/tmp"
  )
  if [[ -x "$LOCAL_EDM_FFMPEG_BIN_DIR/ffprobe" && -x "$LOCAL_EDM_FFMPEG_BIN_DIR/ffmpeg" ]]; then
    echo "Using local EDM FFmpeg tools from $LOCAL_EDM_FFMPEG_BIN_DIR"
    local_edm_validator_binds+=(
      -B "$LOCAL_EDM_FFMPEG_BIN_DIR/ffprobe:/usr/bin/ffprobe:ro"
      -B "$LOCAL_EDM_FFMPEG_BIN_DIR/ffmpeg:/usr/bin/ffmpeg:ro"
    )
    if [[ -x "$LOCAL_EDM_FFMPEG_BIN_DIR/ffprobe.real" ]]; then
      local_edm_validator_binds+=(
        -B "$LOCAL_EDM_FFMPEG_BIN_DIR/ffprobe.real:/usr/bin/ffprobe.real:ro"
      )
    fi
  elif [[ "$LOCAL_EDM_VALIDATOR_REQUIRED" == "true" ]]; then
    echo "Missing FFmpeg 8 tools in $LOCAL_EDM_FFMPEG_BIN_DIR; Local EDM Validator is required" >&2
    exit 1
  fi
  if [[ -f "$LOCAL_EDM_VALIDATOR_APP_JAR" ]]; then
    if ! unzip -Z1 "$LOCAL_EDM_VALIDATOR_APP_JAR" | grep -Fx 'BOOT-INF/lib/metis-schema-15.jar' >/dev/null; then
      echo "The validator app JAR at $LOCAL_EDM_VALIDATOR_APP_JAR must contain Metis Schema 15." >&2
      echo "Rebuild the validator SIF and regenerate the override with scripts/hpc_singularity/remote/patch_local_edm_validator_jar.sh." >&2
      exit 1
    fi
    echo "Using patched local EDM validator app JAR from $LOCAL_EDM_VALIDATOR_APP_JAR"
    local_edm_validator_binds+=(
      -B "$LOCAL_EDM_VALIDATOR_APP_JAR:/app.jar:ro"
    )
  fi

  start_with_pidfile "local_edm_validator" "$PID_DIR/local_edm_validator.pid" \
    singularity exec --cleanenv "${proxy_env_opts[@]}" \
      --env SPRING_CONFIG_ADDITIONAL_LOCATION=file:/config/application.yml \
      --env JDK_JAVA_OPTIONS="${LOCAL_EDM_VALIDATOR_JAVA_OPTIONS:--Xms500m -Xmx1g}" \
      "${local_edm_validator_binds[@]}" \
      "$SIF_DIR/local-edm-validator.sif" \
      java -jar /app.jar --server.port="$LOCAL_EDM_VALIDATOR_PORT"
  wait_for_http "local_edm_validator" "http://127.0.0.1:${LOCAL_EDM_VALIDATOR_PORT}/actuator/health" 120 5
elif [[ "$LOCAL_EDM_VALIDATOR_REQUIRED" == "true" ]]; then
  wait_for_http "local_edm_validator" "$LOCAL_EDM_VALIDATOR_URL/actuator/health" 30 2
fi

if [[ ! -f "$DB_PATH" ]]; then
  echo "Database missing, running init-data..."
  timeout 300 singularity exec --cleanenv --env-file "$ENV_FILE" "${proxy_env_opts[@]}" "${app_env_opts[@]}" \
    "${common_backend_binds[@]}" \
    "$SIF_DIR/backend.sif" \
    sh -c "cd /app && FLASK_APP=app.py flask init-data" >>"$LOG_DIR/init-data.log" 2>&1 || true
else
  echo "Database exists, skipping init-data"
fi

start_with_pidfile "fast_renderer" "$PID_DIR/fast_renderer.pid" \
  singularity exec --cleanenv --env-file "$ENV_FILE" "${proxy_env_opts[@]}" "${renderer_exec_opts[@]}" \
    --env PORT="$FAST_RENDERER_PORT" \
    --env LIBGL_ALWAYS_SOFTWARE=0 \
    --env BLENDER_EGL_SURFACELESS=1 \
    --env PYOPENGL_PLATFORM=egl \
    --env __GLX_VENDOR_LIBRARY_NAME=nvidia \
    --env __NV_PRIME_RENDER_OFFLOAD=1 \
    --env CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES_VALUE" \
    --env SLURM_GPUS_ON_NODE="$SLURM_GPUS_ON_NODE_VALUE" \
    --env SLURM_STEP_GPUS="$SLURM_STEP_GPUS_VALUE" \
    --env SLURM_JOB_GPUS="$SLURM_JOB_GPUS_VALUE" \
    --env NVIDIA_VISIBLE_DEVICES="$NVIDIA_VISIBLE_DEVICES_VALUE" \
    "${common_renderer_binds[@]}" \
    "$SIF_DIR/fast-renderer.sif" \
    sh -c "cd /app/external_code/fast_renderer && python server.py"

start_with_pidfile "any_to_usdz" "$PID_DIR/any_to_usdz.pid" \
  singularity exec --cleanenv --env-file "$ENV_FILE" "${proxy_env_opts[@]}" "${renderer_exec_opts[@]}" --env PORT="$ANY_TO_USDZ_PORT" \
    "${common_renderer_binds[@]}" \
    "$SIF_DIR/any-to-usdz.sif" \
    sh -c "cd /app && python server.py"

start_with_pidfile "backend" "$PID_DIR/backend.pid" \
  singularity exec --cleanenv --env-file "$ENV_FILE" "${proxy_env_opts[@]}" "${app_env_opts[@]}" \
    "${common_backend_binds[@]}" \
    "$SIF_DIR/backend.sif" \
    sh -c "cd /tmp && export PYTHONPATH=\$PYTHONPATH:/app && gunicorn --bind 0.0.0.0:$BACKEND_PORT --workers 4 --timeout 1200 --pid /runtime/gunicorn-${BACKEND_PORT}.pid --worker-tmp-dir /tmp --access-logfile - --error-logfile - app:app"

start_with_pidfile "celery_worker" "$PID_DIR/celery_worker.pid" \
  singularity exec --cleanenv --env-file "$ENV_FILE" "${proxy_env_opts[@]}" "${app_env_opts[@]}" \
    "${common_worker_binds[@]}" \
    "$SIF_DIR/backend.sif" \
    sh -c "cd /tmp && export PYTHONPATH=\$PYTHONPATH:/app && celery -A celery_app.celery worker --loglevel=info --concurrency=${CELERY_WORKER_CONCURRENCY:-2}"

if [[ "$FRONTEND_IN_SINGULARITY" == "true" ]]; then
  mkdir -p \
    "$RUNTIME_DIR/nginx-cache" \
    "$RUNTIME_DIR/nginx-run" \
    "$RUNTIME_DIR/nginx-log" \
    "$RUNTIME_DIR/nginx-conf"

  frontend_binds=(
    -B "$RUNTIME_DIR/nginx-cache:/var/cache/nginx"
    -B "$RUNTIME_DIR/nginx-run:/var/run"
    -B "$RUNTIME_DIR/nginx-log:/var/log/nginx"
    -B "$RUNTIME_DIR/nginx-conf:/etc/nginx/conf.d"
  )

  if [[ -d "$ROOT/frontend-dist" ]]; then
    frontend_binds+=(-B "$ROOT/frontend-dist:/usr/share/nginx/html:ro")
  fi

  start_with_pidfile "frontend" "$PID_DIR/frontend.pid" \
    singularity exec --cleanenv --env-file "$ENV_FILE" "${proxy_env_opts[@]}" \
      --env FRONTEND_PORT="$FRONTEND_PORT" \
      --env BACKEND_PORT="$BACKEND_PORT" \
      "${frontend_binds[@]}" \
      "$SIF_DIR/frontend.sif" \
      /docker-entrypoint.sh nginx -g "daemon off;"
fi

for _ in $(seq 1 60); do
  if service_health_ok; then
    if [[ -n "${WEBHDP_JOB_COMMAND:-}" || -n "${WEBHDP_BATCH_CHUNK_JSON:-}" || "${WEBHDP_START_SERVICES_RETURN_AFTER_HEALTH:-false}" == "true" ]]; then
      echo "All services healthy. Returning to caller..."
      exit 0
    fi
    watch_services_forever
  fi
  sleep 2
done

echo "Service health checks did not fully pass in time" >&2
exit 1
