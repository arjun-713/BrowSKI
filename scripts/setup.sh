#!/usr/bin/env bash
set -euo pipefail
# Bootstrap developer environment: toolchains, Python venv, bindings.

cd "$(dirname "$0")/.."

echo "==> Rust toolchain"
cargo --version
rustc --version

echo "==> Python / uv"
uv --version
python3 --version

if [ -z "${CHROME_PATH:-}" ]; then
  for bin in google-chrome-stable google-chrome chromium chromium-browser; do
    if command -v "$bin" >/dev/null 2>&1; then
      echo "Found browser: $bin ($(command -v "$bin"))"
      break
    fi
  done
else
  echo "CHROME_PATH=$CHROME_PATH"
fi

echo "==> Rust build"
cargo build --workspace

echo "==> Python venv + bindings"
cd python
uv sync --extra test

echo "Setup complete. Try: make test && make example"
