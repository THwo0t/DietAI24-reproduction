#!/usr/bin/env bash
# Project-local Python and dependencies; no Homebrew, sudo or shell-profile edits.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-offline}"
case "$MODE" in offline|live) ;; *) echo 'Usage: ./setup.sh [offline|live]' >&2; exit 2;; esac
UV="$ROOT/.tools/uv/uv"
if [[ ! -x "$UV" ]]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) TRIPLE=aarch64-apple-darwin; SHA=892e8ac6d5240a4dec21fac5bedef52c1b6d40f0dfe52f9e3203038e7e16aed2 ;;
    Darwin-x86_64) TRIPLE=x86_64-apple-darwin; SHA=b47e42976ff4749f960b9030f5948c1af0b51ef944293de266a6cc10cecef9c7 ;;
    Linux-x86_64) TRIPLE=x86_64-unknown-linux-gnu; SHA=ccf643248118d5ed85698161e4456f384ff3ec1f20a9f89e4daa9f4de1b4ab6f ;;
    *) echo 'Supported: macOS Apple Silicon or Intel, Linux x86_64.' >&2; exit 2 ;;
  esac
  mkdir -p "$ROOT/.tools/uv"
  WORK="$(mktemp -d "$ROOT/.tools/uv-install.XXXXXX")"
  trap 'rm -rf "$WORK"' EXIT
  curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
    "https://github.com/astral-sh/uv/releases/download/0.9.6/uv-$TRIPLE.tar.gz" -o "$WORK/uv.tar.gz"
  ACTUAL="$(shasum -a 256 "$WORK/uv.tar.gz" | awk '{print $1}')"
  [[ "$ACTUAL" == "$SHA" ]] || { echo 'uv checksum mismatch; stopped.' >&2; exit 1; }
  tar -xzf "$WORK/uv.tar.gz" -C "$WORK" "uv-$TRIPLE/uv"
  cp "$WORK/uv-$TRIPLE/uv" "$UV"
  chmod +x "$UV"
fi
export UV_PYTHON_INSTALL_DIR="$ROOT/.tools/python"
export UV_CACHE_DIR="$ROOT/.tools/cache"
"$UV" python install 3.10.13
if [[ ! -x "$ROOT/.venv-demo/bin/python" ]]; then
  "$UV" venv --python 3.10.13 "$ROOT/.venv-demo"
fi
"$ROOT/.venv-demo/bin/python" -c 'import sys; assert sys.version_info[:3] == (3,10,13), "Use a fresh .venv-demo with Python 3.10.13"'
"$UV" pip sync --python "$ROOT/.venv-demo/bin/python" "$ROOT/env/pip-freeze.txt"
"$ROOT/.venv-demo/bin/python" "$ROOT/tools/demo.py" --check
if [[ "$MODE" == live ]]; then
  "$ROOT/.venv-demo/bin/python" "$ROOT/tools/runtime_bundle.py" install
  "$ROOT/.venv-demo/bin/python" "$ROOT/tools/live_demo.py" --dry-run
fi
echo "Ready. Offline: $ROOT/.venv-demo/bin/python tools/demo.py --open"
