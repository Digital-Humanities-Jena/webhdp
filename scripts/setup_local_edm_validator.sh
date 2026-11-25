#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_REPO_URL="https://github.com/Digital-Humanities-Jena/local-edm-validator.git"
DEFAULT_REF="443227fa3d715e398f21e6b2dd07bab3ee841349"
EDM_SCHEMA_VERSION="20260720"
TARGET_DIR="${LOCAL_EDM_VALIDATOR_REPO:-$ROOT_DIR/external_code/local-edm-validator}"
METIS_SCHEMA_PATH="metis-sandbox-rest/webhdp-metis-schema"
REPO_URL="${LOCAL_EDM_VALIDATOR_SOURCE_REPOSITORY:-$DEFAULT_REPO_URL}"
PINNED_REF="${LOCAL_EDM_VALIDATOR_SOURCE_REF:-$DEFAULT_REF}"
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
  --force        Fetch the pinned commit again before verifying an up-to-date checkout.
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

# Released WebHDP versions patched two files in the validator checkout.
# Clear those exact files when upgrading a managed checkout.
restore_legacy_patch() {
  local path blob
  local files=()
  local changes_message="$TARGET_DIR has local changes. Commit or stash them before switching refs."
  git -C "$TARGET_DIR" diff --cached --quiet || fail "$changes_message"
  [[ -z "$(git -C "$TARGET_DIR" ls-files --others --exclude-standard)" ]] || fail "$changes_message"
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    blob="$(git -C "$TARGET_DIR" hash-object "$path")" || fail "$changes_message"
    case "$path:$blob" in
      metis-sandbox-rest/Dockerfile.local:fdb027c78dbb004f7b2eb51f521ecd1e31bd05f8|\
      metis-sandbox-rest/docker/local/application.yml:c73a545dc38043c0bc303518541ca7299d35d045)
        files+=("$path")
        ;;
      *) fail "$changes_message" ;;
    esac
  done <<<"$(git -C "$TARGET_DIR" diff --name-only)"
  if [[ ${#files[@]} -gt 0 ]]; then
    git -C "$TARGET_DIR" restore --worktree -- "${files[@]}"
  fi
}

if [[ ! -e "$TARGET_DIR/.git" ]]; then
  if [[ "$VERIFY_ONLY" == "true" ]]; then
    fail "Missing local-edm-validator git checkout at $TARGET_DIR"
  fi
  if [[ -e "$TARGET_DIR" ]] && [[ -n "$(find "$TARGET_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    fail "$TARGET_DIR exists but is not an empty git checkout. Move it aside or set LOCAL_EDM_VALIDATOR_REPO."
  fi
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
  git -C "$TARGET_DIR" fetch --tags origin "$PINNED_REF"
  if [[ "$current_ref" == "b1ba67802ae1581c88ba8ea0ae9740cf663a0176" ]]; then
    restore_legacy_patch
  fi
  [[ -z "$(git -C "$TARGET_DIR" status --porcelain)" ]] || fail "$TARGET_DIR has local changes. Commit or stash them before switching refs."
  git -C "$TARGET_DIR" checkout --detach "$PINNED_REF"
elif [[ "$FORCE" == "true" && "$VERIFY_ONLY" != "true" ]]; then
  git -C "$TARGET_DIR" fetch --tags origin "$PINNED_REF"
fi

# The validator builds the schema and JiBX bindings from its pinned submodule.
if [[ "$VERIFY_ONLY" != "true" ]]; then
  git -C "$TARGET_DIR" submodule update --init -- "$METIS_SCHEMA_PATH"
fi
metis_schema_status="$(git -C "$TARGET_DIR" submodule status -- "$METIS_SCHEMA_PATH")"
[[ "$metis_schema_status" == " "* ]] || fail "Metis Schema submodule is missing or at a different revision. Run setup again."
[[ -z "$(git -C "$TARGET_DIR" status --porcelain)" ]] || fail "$TARGET_DIR has local changes."

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

echo "local-edm-validator checkout ready"
echo "  path:       $TARGET_DIR"
echo "  upstream:   $REPO_URL"
echo "  source ref: $PINNED_REF"
echo "  EDM schema: $EDM_SCHEMA_VERSION (Metis Schema${metis_schema_status})"
echo
echo "Use this source ref when building:"
echo "  export LOCAL_EDM_VALIDATOR_SOURCE_REF=$PINNED_REF"
echo "  export LOCAL_EDM_VALIDATOR_IMAGE=local-edm-validator:webhdp-$(short_ref "$PINNED_REF")-edm-$EDM_SCHEMA_VERSION"
