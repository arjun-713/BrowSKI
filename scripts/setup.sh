#!/usr/bin/env bash
set -euo pipefail
# Bootstrap the Linux development environment and build the unpacked extension.

cd "$(dirname "$0")/.."

echo "==> Rust toolchain"
cargo --version
rustc --version

echo "==> Python / uv"
uv --version
python3 --version

echo "==> Node / npm"
node --version
npm --version

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
uv sync --project python --extra dev
uv run --project python maturin develop --manifest-path crates/python-bindings/Cargo.toml

echo "==> Browser extension"
cd extension
npm ci
npm run build

echo "Development setup complete. Try: make test && make example"
