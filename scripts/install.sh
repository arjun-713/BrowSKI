#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'USAGE'
Usage: scripts/install.sh [--help | --preflight]

Build BROWSKI's local Linux development environment and both MV3 extension
outputs. Tooling and dependencies stay in the checkout's Python virtual
environment, Cargo target directory, and extension/node_modules directory.
No global package or browser configuration is changed.

Options:
  --preflight  Check supported platform and required tools without writing files.
  -h, --help   Show this help.
USAGE
}

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

check_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 \
    || fail "required command not found: $command_name"
}

preflight() {
  [[ "$(uname -s)" == "Linux" ]] \
    || fail "supported platform: Linux x86_64; detected $(uname -s)"

  case "$(uname -m)" in
    x86_64 | amd64) ;;
    *) fail "supported architecture: x86_64; detected $(uname -m)" ;;
  esac

  local required_command
  for required_command in python3 uv cargo rustc node npm; do
    check_command "$required_command"
  done

  python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
    || fail "Python 3.12 or newer is required"

  local node_major
  node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
  [[ "$node_major" =~ ^[0-9]+$ ]] \
    || fail "could not determine the Node.js major version"
  (( node_major >= 22 )) \
    || fail "Node.js 22 or newer is required; detected $(node --version)"

  if [[ -n "${CHROME_PATH:-}" ]]; then
    [[ -x "$CHROME_PATH" ]] \
      || fail "CHROME_PATH must point to an executable browser binary"
  elif ! command -v google-chrome-stable >/dev/null 2>&1 \
    && ! command -v google-chrome >/dev/null 2>&1 \
    && ! command -v chromium >/dev/null 2>&1 \
    && ! command -v chromium-browser >/dev/null 2>&1; then
    fail "Google Chrome or Chromium is required; set CHROME_PATH to its binary"
  fi

  printf 'Preflight passed for Linux x86_64.\n'
  printf 'Python: %s\n' "$(python3 --version)"
  printf 'uv: %s\n' "$(uv --version)"
  printf 'Rust: %s\n' "$(rustc --version)"
  printf 'Node: %s\n' "$(node --version)"
  printf 'npm: %s\n' "$(npm --version)"
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
  --preflight)
    [[ "$#" -eq 1 ]] || fail "--preflight does not accept additional arguments"
    preflight
    exit 0
    ;;
  "") ;;
  *)
    usage >&2
    fail "unknown argument: $1"
    ;;
esac

cd "$ROOT_DIR"
preflight

printf '\n==> Sync the checkout-local Python environment\n'
uv sync --locked --project "$ROOT_DIR/python" --extra dev

printf '\n==> Build the Rust workspace\n'
cargo build --workspace

printf '\n==> Build the Python bindings in the checkout-local environment\n'
(
  cd "$ROOT_DIR/python"
  uv run maturin develop
)

printf '\n==> Install locked extension dependencies in extension/node_modules\n'
npm --prefix "$ROOT_DIR/extension" ci

printf '\n==> Build the development MV3 extension\n'
npm --prefix "$ROOT_DIR/extension" run build -- --mode development

printf '\n==> Build the production MV3 extension\n'
npm --prefix "$ROOT_DIR/extension" run build -- --mode production

printf '\nInstallation build complete.\n'
printf 'Development extension: %s\n' "$ROOT_DIR/extension/.output/chrome-mv3-dev"
printf 'Production extension:  %s\n' "$ROOT_DIR/extension/.output/chrome-mv3"
printf 'Runtime commands: uv run --project %s browski --help\n' "$ROOT_DIR/python"
printf 'Prerequisite report: uv run --project %s browski doctor\n' "$ROOT_DIR/python"
