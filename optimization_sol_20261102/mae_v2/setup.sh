#!/usr/bin/env bash
# Everything installed here; no Homebrew, sudo, shell-profile or global Python edits.
set -euo pipefail
DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_MODE="${1:-offline}"
case "$DEMO_MODE" in offline|live) ;; *) echo 'Usage: bash setup.sh [offline|live]' >&2; exit 2;; esac
DEMO_UV="$DEMO_ROOT/.tools/uv/uv"
if [[ ! -x "$DEMO_UV" && -x "$DEMO_ROOT/../.tools/uv/uv" ]]; then
  # Optional reuse on the development host; no parent path is required in a release.
  mkdir -p "$DEMO_ROOT/.tools/uv"
  cp "$DEMO_ROOT/../.tools/uv/uv" "$DEMO_UV"
fi
if [[ ! -x "$DEMO_UV" ]]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) DEMO_TRIPLE=aarch64-apple-darwin; DEMO_SHA=892e8ac6d5240a4dec21fac5bedef52c1b6d40f0dfe52f9e3203038e7e16aed2 ;;
    Darwin-x86_64) DEMO_TRIPLE=x86_64-apple-darwin; DEMO_SHA=b47e42976ff4749f960b9030f5948c1af0b51ef944293de266a6cc10cecef9c7 ;;
    Linux-x86_64) DEMO_TRIPLE=x86_64-unknown-linux-gnu; DEMO_SHA=ccf643248118d5ed85698161e4456f384ff3ec1f20a9f89e4daa9f4de1b4ab6f ;;
    *) echo 'Supported: macOS Apple Silicon or Intel, Linux x86_64.' >&2; exit 2 ;;
  esac
  mkdir -p "$DEMO_ROOT/.tools/uv"
  DEMO_WORK="$(mktemp -d "$DEMO_ROOT/.tools/uv-install.XXXXXX")"
  trap 'rm -rf "$DEMO_WORK"' EXIT
  curl --disable --fail --location --retry 3 --proto '=https' --tlsv1.2 \
    "https://github.com/astral-sh/uv/releases/download/0.9.6/uv-$DEMO_TRIPLE.tar.gz" -o "$DEMO_WORK/uv.tar.gz"
  DEMO_ACTUAL="$(shasum -a 256 "$DEMO_WORK/uv.tar.gz" | awk '{print $1}')"
  [[ "$DEMO_ACTUAL" == "$DEMO_SHA" ]] || { echo 'uv checksum mismatch; stopped.' >&2; exit 1; }
  tar -xzf "$DEMO_WORK/uv.tar.gz" -C "$DEMO_WORK" "uv-$DEMO_TRIPLE/uv"
  cp "$DEMO_WORK/uv-$DEMO_TRIPLE/uv" "$DEMO_UV"
  chmod +x "$DEMO_UV"
fi
export UV_PYTHON_INSTALL_DIR="$DEMO_ROOT/.tools/python"
export UV_CACHE_DIR="$DEMO_ROOT/.tools/cache"
export PIP_CACHE_DIR="$DEMO_ROOT/.tools/pip-cache"
export PYTHONDONTWRITEBYTECODE=1
"$DEMO_UV" python install --no-bin 3.10.13
if [[ ! -x "$DEMO_ROOT/.venv-demo/bin/python" ]]; then
  "$DEMO_UV" venv --python 3.10.13 "$DEMO_ROOT/.venv-demo"
fi
"$DEMO_ROOT/.venv-demo/bin/python" -c 'import sys; assert sys.version_info[:3] == (3,10,13), "Use a fresh .venv-demo with Python 3.10.13"'
"$DEMO_UV" pip sync --python "$DEMO_ROOT/.venv-demo/bin/python" "$DEMO_ROOT/requirements-demo.txt"
if [[ "$DEMO_MODE" == live ]]; then
  "$DEMO_ROOT/.venv-demo/bin/python" "$DEMO_ROOT/tools/demo.py" --check --require-runtime
else
  "$DEMO_ROOT/.venv-demo/bin/python" "$DEMO_ROOT/tools/demo.py" --check
fi
echo 'Environment ready. This script submitted zero model requests.'
