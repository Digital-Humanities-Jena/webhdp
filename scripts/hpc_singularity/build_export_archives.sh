#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/artifacts/hpc_singularity}"
PLATFORM="${PLATFORM:-linux/amd64}"
TAG="${TAG:-singularity-latest}"
INCLUDE_LOCAL_EDM_VALIDATOR="${INCLUDE_LOCAL_EDM_VALIDATOR:-true}"

mkdir -p "$OUT_DIR"

build_image() {
  local name="$1"
  local dockerfile="$2"
  local context="$3"
  local image_tag="$4"

  echo "==> Building $name ($image_tag) for $PLATFORM"
  docker buildx build \
    --platform "$PLATFORM" \
    --load \
    -f "$dockerfile" \
    -t "$image_tag" \
    "$context"
}

build_from_public_base() {
  local name="$1"
  local base_image="$2"
  local image_tag="$3"
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  printf 'FROM --platform=%s %s\n' "$PLATFORM" "$base_image" >"$tmp_dir/Dockerfile"

  echo "==> Building $name from $base_image ($image_tag) for $PLATFORM"
  docker buildx build \
    --platform "$PLATFORM" \
    --load \
    -f "$tmp_dir/Dockerfile" \
    -t "$image_tag" \
    "$tmp_dir"
  rm -rf "$tmp_dir"
}

save_image() {
  local image_tag="$1"
  local out_tar="$2"
  echo "==> Exporting $image_tag -> $out_tar"
  docker save -o "$out_tar" "$image_tag"
  ls -lh "$out_tar"
}

# Build project images
build_image "backend" "$ROOT_DIR/backend/Dockerfile" "$ROOT_DIR" "webhdp-backend:$TAG"
build_image "fast-renderer" "$ROOT_DIR/external_code/fast_renderer/Dockerfile" "$ROOT_DIR/external_code/fast_renderer" "webhdp-fast-renderer:$TAG"
build_image "any-to-usdz" "$ROOT_DIR/external_code/any_to_usdz/Dockerfile" "$ROOT_DIR/external_code/any_to_usdz" "webhdp-any-to-usdz:$TAG"

# Pin redis image for consistent runtime.
build_from_public_base "redis" "redis:7-alpine" "webhdp-redis:$TAG"

if [[ "$INCLUDE_LOCAL_EDM_VALIDATOR" == "true" ]]; then
  bash "$ROOT_DIR/scripts/setup_local_edm_validator.sh" --verify-only
  build_image "local-edm-solr" \
    "$ROOT_DIR/external_code/local-edm-validator/metis-sandbox-rest/docker/solr/Dockerfile" \
    "$ROOT_DIR/external_code/local-edm-validator/metis-sandbox-rest/docker/solr" \
    "webhdp-local-edm-solr:$TAG"
  build_image "local-edm-validator" \
    "$ROOT_DIR/external_code/local-edm-validator/metis-sandbox-rest/Dockerfile.local" \
    "$ROOT_DIR/external_code/local-edm-validator" \
    "webhdp-local-edm-validator:$TAG"

  build_from_public_base "local-edm-postgres" "postgres:17-alpine" "webhdp-local-edm-postgres:$TAG"
  build_from_public_base "local-edm-mongo" "mongo:6.0.12" "webhdp-local-edm-mongo:$TAG"
  build_from_public_base "local-edm-minio" "minio/minio:latest" "webhdp-local-edm-minio:$TAG"
  build_from_public_base "local-edm-mc" "minio/mc:latest" "webhdp-local-edm-mc:$TAG"
fi

# Save archives
save_image "webhdp-backend:$TAG" "$OUT_DIR/backend.tar"
save_image "webhdp-fast-renderer:$TAG" "$OUT_DIR/fast-renderer.tar"
save_image "webhdp-any-to-usdz:$TAG" "$OUT_DIR/any-to-usdz.tar"
save_image "webhdp-redis:$TAG" "$OUT_DIR/redis.tar"

checksum_targets=(backend.tar fast-renderer.tar any-to-usdz.tar redis.tar)

if [[ "$INCLUDE_LOCAL_EDM_VALIDATOR" == "true" ]]; then
  save_image "webhdp-local-edm-postgres:$TAG" "$OUT_DIR/local-edm-postgres.tar"
  save_image "webhdp-local-edm-mongo:$TAG" "$OUT_DIR/local-edm-mongo.tar"
  save_image "webhdp-local-edm-solr:$TAG" "$OUT_DIR/local-edm-solr.tar"
  save_image "webhdp-local-edm-minio:$TAG" "$OUT_DIR/local-edm-minio.tar"
  save_image "webhdp-local-edm-mc:$TAG" "$OUT_DIR/local-edm-mc.tar"
  save_image "webhdp-local-edm-validator:$TAG" "$OUT_DIR/local-edm-validator.tar"
  checksum_targets+=(
    local-edm-postgres.tar
    local-edm-mongo.tar
    local-edm-solr.tar
    local-edm-minio.tar
    local-edm-mc.tar
    local-edm-validator.tar
  )
fi

echo "==> Writing checksums"
(
  cd "$OUT_DIR"
  shasum -a 256 "${checksum_targets[@]}" > SHA256SUMS
)

echo "Done. Archives in: $OUT_DIR"
