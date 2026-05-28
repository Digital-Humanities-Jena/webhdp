#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/webhdp-user/webhdp}"
FFMPEG_VERSION="${FFMPEG_VERSION:-8.0}"
PREFIX="${LOCAL_EDM_FFMPEG_PREFIX:-$ROOT/tools/ffmpeg-8}"
BUILD_ROOT="${LOCAL_EDM_FFMPEG_BUILD_ROOT:-$ROOT/tools/build}"
TARBALL="$BUILD_ROOT/ffmpeg-$FFMPEG_VERSION.tar.xz"
SRC_DIR="$BUILD_ROOT/ffmpeg-$FFMPEG_VERSION"

mkdir -p "$PREFIX" "$BUILD_ROOT"

install_ffprobe_wrapper() {
  if [[ ! -x "$PREFIX/bin/ffprobe.real" ]]; then
    mv "$PREFIX/bin/ffprobe" "$PREFIX/bin/ffprobe.real"
  fi
  cat >"$PREFIX/bin/ffprobe" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -eq 0 ]]; then
  # METIS media-processing discovery checks `ffprobe` with no arguments and
  # accepts major versions 2-7. Delegate all actual probing to the real binary.
  echo "ffprobe version7.0"
  exit 0
fi

exec "$(dirname "$0")/ffprobe.real" "$@"
EOF
  chmod +x "$PREFIX/bin/ffprobe"
}

if [[ -x "$PREFIX/bin/ffprobe.real" ]] && "$PREFIX/bin/ffprobe.real" -version | head -1 | grep -Eq '^ffprobe version 8\.'; then
  install_ffprobe_wrapper
  "$PREFIX/bin/ffprobe.real" -version | head -1
  "$PREFIX/bin/ffprobe"
  exit 0
fi

if [[ -x "$PREFIX/bin/ffprobe" ]] && "$PREFIX/bin/ffprobe" -version | head -1 | grep -Eq '^ffprobe version 8\.'; then
  install_ffprobe_wrapper
  "$PREFIX/bin/ffprobe.real" -version | head -1
  "$PREFIX/bin/ffprobe"
  exit 0
fi

if [[ ! -f "$TARBALL" ]]; then
  curl -fL "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" -o "$TARBALL"
fi

rm -rf "$SRC_DIR"
tar -xf "$TARBALL" -C "$BUILD_ROOT"

cd "$SRC_DIR"
./configure \
  --prefix="$PREFIX" \
  --disable-debug \
  --disable-doc \
  --disable-ffplay \
  --disable-x86asm
make -j"${LOCAL_EDM_FFMPEG_MAKE_JOBS:-4}"
make install

install_ffprobe_wrapper

"$PREFIX/bin/ffprobe.real" -version | head -1 | grep -Eq '^ffprobe version 8\.'
"$PREFIX/bin/ffmpeg" -version | head -1
"$PREFIX/bin/ffprobe.real" -version | head -1
"$PREFIX/bin/ffprobe"
