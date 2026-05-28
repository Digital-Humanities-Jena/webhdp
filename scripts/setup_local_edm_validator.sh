#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_REPO_URL="https://github.com/Digital-Humanities-Jena/local-edm-validator.git"
DEFAULT_REF="b1ba67802ae1581c88ba8ea0ae9740cf663a0176"
TARGET_DIR="${LOCAL_EDM_VALIDATOR_REPO:-$ROOT_DIR/external_code/local-edm-validator}"
REPO_URL="${LOCAL_EDM_VALIDATOR_SOURCE_REPOSITORY:-$DEFAULT_REPO_URL}"
PINNED_REF="${LOCAL_EDM_VALIDATOR_SOURCE_REF:-$DEFAULT_REF}"
PATCH_FILE="$ROOT_DIR/patches/local-edm-validator/webhdp-dockerfile-local.patch"
VERIFY_ONLY=false
FORCE=false

usage() {
  cat <<USAGE
Usage: scripts/setup_local_edm_validator.sh [--verify-only] [--force]

Clone or verify the pinned local-edm-validator source checkout used by WebHDP.

Environment:
  LOCAL_EDM_VALIDATOR_REPO               Target checkout path
  LOCAL_EDM_VALIDATOR_SOURCE_REPOSITORY  Upstream repository URL
  LOCAL_EDM_VALIDATOR_SOURCE_REF         Pinned upstream commit

Options:
  --verify-only  Check the current checkout without cloning or changing files.
  --force        Allow replacing an existing wrong checkout when it is clean.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-only)
      VERIFY_ONLY=true
      ;;
    --force)
      FORCE=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

short_ref() {
  printf '%s' "$1" | cut -c1-12
}

ensure_patch_state() {
  if git -C "$TARGET_DIR" apply --unidiff-zero --reverse --check "$PATCH_FILE" >/dev/null 2>&1; then
    return 0
  fi
  if [[ "$VERIFY_ONLY" == "true" ]]; then
    fail "WebHDP local-edm-validator patch is not applied in $TARGET_DIR"
  fi
  if git -C "$TARGET_DIR" apply --unidiff-zero --check "$PATCH_FILE" >/dev/null 2>&1; then
    git -C "$TARGET_DIR" apply --unidiff-zero "$PATCH_FILE"
    return 0
  fi
  fail "Cannot apply WebHDP patch cleanly: $PATCH_FILE"
}

if [[ ! -f "$PATCH_FILE" ]]; then
  fail "Missing WebHDP patch file: $PATCH_FILE"
fi

if [[ ! -d "$TARGET_DIR/.git" ]]; then
  if [[ "$VERIFY_ONLY" == "true" ]]; then
    fail "Missing local-edm-validator git checkout at $TARGET_DIR"
  fi
  if [[ -e "$TARGET_DIR" ]] && [[ -n "$(find "$TARGET_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    fail "$TARGET_DIR exists but is not an empty git checkout. Move it aside or set LOCAL_EDM_VALIDATOR_REPO."
  fi
  rm -rf "$TARGET_DIR"
  git clone "$REPO_URL" "$TARGET_DIR"
fi

actual_url="$(git -C "$TARGET_DIR" remote get-url origin 2>/dev/null || true)"
if [[ -n "$actual_url" && "$actual_url" != "$REPO_URL" && "$actual_url" != "${REPO_URL%.git}" ]]; then
  echo "WARNING: origin URL is $actual_url, expected $REPO_URL" >&2
fi

current_ref="$(git -C "$TARGET_DIR" rev-parse HEAD)"
if [[ "$current_ref" != "$PINNED_REF" ]]; then
  if [[ "$VERIFY_ONLY" == "true" ]]; then
    fail "local-edm-validator is at $current_ref, expected $PINNED_REF"
  fi
  if [[ -n "$(git -C "$TARGET_DIR" status --porcelain)" ]]; then
    fail "$TARGET_DIR has local changes. Commit/stash them or use a clean checkout before switching refs."
  fi
  git -C "$TARGET_DIR" fetch --tags origin "$PINNED_REF"
  git -C "$TARGET_DIR" checkout --detach "$PINNED_REF"
elif [[ "$FORCE" == "true" && "$VERIFY_ONLY" != "true" ]]; then
  git -C "$TARGET_DIR" fetch --tags origin "$PINNED_REF" || true
fi

ensure_patch_state

for required_path in \
  metis-sandbox-rest/Dockerfile.local \
  metis-sandbox-rest/docker/local/application.yml \
  metis-sandbox-rest/docker/solr/Dockerfile; do
  [[ -f "$TARGET_DIR/$required_path" ]] || fail "Missing required validator file: $TARGET_DIR/$required_path"
done

actual_ref="$(git -C "$TARGET_DIR" rev-parse HEAD)"
if [[ "$actual_ref" != "$PINNED_REF" ]]; then
  fail "local-edm-validator is at $actual_ref, expected $PINNED_REF"
fi

if ! git -C "$TARGET_DIR" apply --unidiff-zero --reverse --check "$PATCH_FILE" >/dev/null 2>&1; then
  fail "WebHDP local-edm-validator patch verification failed"
fi

echo "local-edm-validator checkout ready"
echo "  path:       $TARGET_DIR"
echo "  upstream:   $REPO_URL"
echo "  source ref: $PINNED_REF"
echo "  patch:      $PATCH_FILE"
echo
echo "Use this source ref when building:"
echo "  export LOCAL_EDM_VALIDATOR_SOURCE_REF=$PINNED_REF"
echo "  export LOCAL_EDM_VALIDATOR_IMAGE=local-edm-validator:webhdp-$(short_ref "$PINNED_REF")"
