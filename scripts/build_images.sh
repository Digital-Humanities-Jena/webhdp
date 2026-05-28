#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -n "${WEBHDP_IMAGE_TAG:-}" ]]; then
  TAG="$WEBHDP_IMAGE_TAG"
else
  TAG="$(python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("version.json").read_text(encoding="utf-8"))
print(payload.get("version") or "0.1.0-alpha.1")
PY
)"
fi
if [[ ! "${ALLOW_MUTABLE_IMAGE_TAGS:-}" =~ ^(1|true|yes|on)$ && "$TAG" =~ ^(latest|local|dev|development|main|master)$ ]]; then
  echo "Refusing mutable image tag: ${TAG}" >&2
  exit 1
fi
BACKEND_IMAGE="${WEBHDP_BACKEND_IMAGE:-webhdp-backend:${TAG}}"
FRONTEND_IMAGE="${WEBHDP_FRONTEND_IMAGE:-webhdp-frontend:${TAG}}"
FAST_RENDERER_IMAGE="${WEBHDP_FAST_RENDERER_IMAGE:-webhdp-fast-renderer:${TAG}}"
ANY_TO_USDZ_IMAGE="${WEBHDP_ANY_TO_USDZ_IMAGE:-webhdp-any-to-usdz:${TAG}}"

echo "==> Building backend image: ${BACKEND_IMAGE}"
docker build -f backend/Dockerfile -t "$BACKEND_IMAGE" .

echo "==> Building frontend image: ${FRONTEND_IMAGE}"
docker build -f frontend/Dockerfile -t "$FRONTEND_IMAGE" frontend

echo "==> Building fast-renderer image: ${FAST_RENDERER_IMAGE}"
docker build -f external_code/fast_renderer/Dockerfile -t "$FAST_RENDERER_IMAGE" external_code/fast_renderer

echo "==> Building any-to-usdz image: ${ANY_TO_USDZ_IMAGE}"
docker build -f external_code/any_to_usdz/Dockerfile -t "$ANY_TO_USDZ_IMAGE" external_code/any_to_usdz

echo "Image build completed for tag: ${TAG}"
