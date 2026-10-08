#!/usr/bin/env bash
# Keep both local services running; Ctrl+C stops only processes started here.
set -euo pipefail
umask 077

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_python="$repo_root/python/.venv/bin/python"
laya_command="${LAYA_SERVE_BIN:-$repo_root/../Agent-Browser-Benchmark/.venv/bin/laya-serve}"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/browski"
owned_pids=()

cleanup() {
  trap - EXIT INT TERM
  for pid in "${owned_pids[@]}"; do
    kill -INT "$pid" 2>/dev/null || true
  done
  for pid in "${owned_pids[@]}"; do
    for _attempt in {1..50}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
      for _attempt in {1..50}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
    fi
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

launch_service() {
  # Bash background jobs inherit ignored SIGINT; restore it before exec so
  # Python services can perform their normal graceful shutdown.
  "$runtime_python" - "$@" <<'PY'
import os
import signal
import sys

signal.signal(signal.SIGINT, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])
PY
}

[[ -x "$runtime_python" ]] || {
  printf 'BROWSKI is not installed. Run scripts/install.sh first.\n' >&2
  exit 1
}
mkdir -p -- "$state_dir"

laya_listening() {
  "$runtime_python" - <<'PY'
import socket
with socket.socket() as connection:
    connection.settimeout(1)
    raise SystemExit(connection.connect_ex(("127.0.0.1", 8000)) != 0)
PY
}

laya_ready() {
  "$runtime_python" - <<'PY'
import urllib.error
import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
        raise SystemExit(response.status != 200)
except (OSError, urllib.error.URLError):
    raise SystemExit(1)
PY
}

if laya_listening; then
  printf 'Using the existing service on Laya port 8000.\n'
else
  [[ -x "$laya_command" ]] || {
    printf 'Laya launcher missing. Set LAYA_SERVE_BIN to its installed path.\n' >&2
    exit 1
  }
  LAYA_HOST=127.0.0.1 LAYA_PORT=8000 LAYA_DEVICE=cpu \
    LAYA_MODELS=english LAYA_PRELOAD=1 LAYA_THREADS=4 \
    HF_HUB_OFFLINE=1 launch_service "$laya_command" >"$state_dir/laya.log" 2>&1 &
  owned_pids+=("$!")
  printf 'Starting local CPU Laya; log: %s/laya.log\n' "$state_dir"
fi

ready=false
for _attempt in {1..90}; do
  if laya_ready; then
    ready=true
    break
  fi
  if [[ ${#owned_pids[@]} -gt 0 ]] && ! kill -0 "${owned_pids[0]}" 2>/dev/null; then
    break
  fi
  sleep 2
done
if [[ "$ready" != true ]]; then
  printf 'Laya did not become healthy. Check %s/laya.log\n' "$state_dir" >&2
  exit 1
fi
printf 'Laya ready: http://127.0.0.1:8000/health\n'

cd -- "$repo_root"
launch_service "$repo_root/python/.venv/bin/browski" serve \
  --database "$state_dir/checkpoints.sqlite" >"$state_dir/backend.log" 2>&1 &
backend_pid="$!"
owned_pids+=("$backend_pid")
printf 'Starting extension backend; log: %s/backend.log\n' "$state_dir"
printf 'Chrome unpacked extension: %s/extension/.output/chrome-mv3\n' "$repo_root"
printf 'Keep this terminal open. Ctrl+C stops services started by this script.\n'

wait -n "${owned_pids[@]}"
