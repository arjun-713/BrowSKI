#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Prepare local BROWSKI release artifacts without publishing them.

Usage: scripts/prepare-release.sh [--preflight] [--replace]

Builds the locked Rust workspace, the configured Python wheel, the production
Chrome extension directory and deterministic ZIP, a dependency-license metadata
inventory, and SHA-256 checksums under dist/release-VERSION/.

Options:
  --preflight Check local tools and version alignment without changing files.
  --replace  Replace only dist/release-VERSION after a successful rebuild.
  -h, --help Show this help.

The script uses the repository-local Python environment, extension node_modules,
and ignored dist/ output. It does not publish artifacts or install globally.
EOF
}

fail() {
  printf 'release prep: %s\n' "$*" >&2
  exit 1
}

replace_existing=false
preflight=false
while (($#)); do
  case "$1" in
    --replace) replace_existing=true ;;
    --preflight) preflight=true ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1 (use --help)" ;;
  esac
  shift
done

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/browski-release-uv-cache}"

for tool in cargo rustc uv python3 node npm; do
  command -v "$tool" >/dev/null 2>&1 || fail "required tool '$tool' was not found in PATH"
done

python3 - <<'PY' || fail "Python 3.12 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY

node_major="$(node -p 'Number(process.versions.node.split(".")[0])')" \
  || fail "could not determine the Node.js major version"
((node_major >= 22)) || fail "Node.js 22 or newer is required; found $(node --version)"

versions="$(python3 - <<'PY'
import json
import tomllib
from pathlib import Path

root = Path.cwd()
python_version = tomllib.loads((root / "python/pyproject.toml").read_text())["project"]["version"]
extension_version = json.loads((root / "extension/package.json").read_text())["version"]
if python_version != extension_version:
    raise SystemExit(f"Python version {python_version} differs from extension version {extension_version}")
rust_versions = {
    tomllib.loads(path.read_text())["package"]["version"]
    for path in sorted((root / "crates").glob("*/Cargo.toml"))
}
if rust_versions != {python_version}:
    raise SystemExit(f"Rust crate versions {sorted(rust_versions)} differ from project version {python_version}")
print(python_version)
PY
)" || fail "could not validate the Python and extension versions"

if [[ "$preflight" == true ]]; then
  cargo metadata --locked --no-deps --format-version 1 --manifest-path "$repo_root/Cargo.toml" >/dev/null \
    || fail "Cargo.lock is not consistent with the workspace manifests"
  uv lock --check --offline --directory "$repo_root/python" >/dev/null \
    || fail "python/uv.lock is not consistent with the Python project"
  printf 'Preflight passed for BROWSKI %s\n' "$versions"
  printf 'Python: %s\nuv: %s\nRust: %s\nNode: %s\nnpm: %s\n' \
    "$(python3 --version)" "$(uv --version)" "$(rustc --version)" \
    "$(node --version)" "$(npm --version)"
  exit 0
fi

release_dir="$repo_root/dist/release-$versions"
if [[ -e "$release_dir" && "$replace_existing" != true ]]; then
  fail "$release_dir already exists; use --replace to rebuild that local output"
fi

mkdir -p "$repo_root/dist"
stage_dir="$(mktemp -d "$repo_root/dist/.release-$versions.XXXXXX")"
cleanup() {
  if [[ -n "${stage_dir:-}" && -d "$stage_dir" ]]; then
    rm -rf -- "$stage_dir"
  fi
}
trap cleanup EXIT INT TERM

printf 'Preparing BROWSKI %s locally\n' "$versions"
printf 'Output after success: %s\n' "$release_dir"

# The configured mixed Python/Rust project builds its binding through uv and
# python/pyproject.toml, avoiding standalone native-module packaging.
uv sync --locked --extra dev --directory "$repo_root/python"
cargo build --workspace --release --locked
uv build --wheel --no-build-isolation \
  --no-create-gitignore \
  --python "$repo_root/python/.venv/bin/python" \
  --out-dir "$stage_dir/python" "$repo_root/python"

export npm_config_cache="${npm_config_cache:-/tmp/browski-release-npm-cache}"
npm ci --prefix "$repo_root/extension"
npm run build --prefix "$repo_root/extension"

extension_output="$repo_root/extension/.output/chrome-mv3"
[[ -f "$extension_output/manifest.json" ]] \
  || fail "production extension manifest missing at $extension_output/manifest.json"

mkdir -p "$stage_dir/extension/chrome-mv3" "$stage_dir/reports"
cp -a "$extension_output/." "$stage_dir/extension/chrome-mv3/"
cp "$repo_root/LICENSE" "$stage_dir/LICENSE"
python3 "$repo_root/scripts/license_inventory.py" \
  --repo "$repo_root" \
  --python "$repo_root/python/.venv/bin/python" \
  --output "$stage_dir/reports/dependency-licenses.json"

python3 "$repo_root/scripts/release_artifacts.py" --stage "$stage_dir" --version "$versions"

if [[ -e "$release_dir" ]]; then
  rm -rf -- "$release_dir"
fi
mv -- "$stage_dir" "$release_dir"
stage_dir=""
trap - EXIT INT TERM
printf 'Local release artifacts ready: %s\n' "$release_dir"
printf 'Verify checksums with: (cd %q && sha256sum --check SHA256SUMS)\n' "$release_dir"
