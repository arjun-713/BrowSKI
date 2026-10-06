"""Start the local Laya server and record its CPU/RAM footprint."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_proc_stat(pid: int) -> tuple[int, int] | None:
    try:
        content = Path(f"/proc/{pid}/stat").read_text()
        remainder = content[content.rfind(")") + 2 :].split()
        user_ticks = int(remainder[11])
        system_ticks = int(remainder[12])
        return user_ticks, system_ticks
    except (OSError, ValueError, IndexError):
        return None


def _read_process_rss_bytes(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _read_system_memory() -> tuple[int, int] | None:
    try:
        fields: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, raw_value = line.split(":", maxsplit=1)
            if name in {"MemTotal", "MemAvailable"}:
                fields[name] = int(raw_value.split()[0]) * 1024
        return fields["MemTotal"], fields["MemAvailable"]
    except (OSError, ValueError, KeyError, IndexError):
        return None


def _read_cpu_ticks() -> tuple[int, int] | None:
    try:
        first_line = Path("/proc/stat").read_text().splitlines()[0]
        values = [int(value) for value in first_line.split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle
    except (OSError, ValueError, IndexError):
        return None


def _health_is_ready(endpoint: str) -> bool:
    try:
        with urlopen(f"{endpoint.rstrip('/')}/health", timeout=1) as response:
            payload: Any = json.load(response)
        return (
            response.status == 200
            and isinstance(payload, dict)
            and payload.get("status") == "ok"
        )
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return False


def _write_sample(
    output: Any,
    *,
    pid: int,
    previous_process_ticks: tuple[int, int] | None,
    previous_cpu_ticks: tuple[int, int] | None,
    previous_sample_time: float | None,
) -> tuple[tuple[int, int] | None, tuple[int, int] | None, float]:
    now = time.monotonic()
    process_ticks = _read_proc_stat(pid)
    cpu_ticks = _read_cpu_ticks()
    rss_bytes = _read_process_rss_bytes(pid)
    memory = _read_system_memory()
    elapsed = now - previous_sample_time if previous_sample_time is not None else None

    process_cpu_seconds = None
    process_cpu_percent_of_machine = None
    if process_ticks is not None and previous_process_ticks is not None and elapsed:
        ticks = (process_ticks[0] - previous_process_ticks[0]) + (
            process_ticks[1] - previous_process_ticks[1]
        )
        process_cpu_seconds = ticks / os.sysconf("SC_CLK_TCK")
        cpu_count = os.cpu_count() or 1
        process_cpu_percent_of_machine = process_cpu_seconds / elapsed / cpu_count * 100

    system_cpu_percent = None
    if cpu_ticks is not None and previous_cpu_ticks is not None:
        total_delta = cpu_ticks[0] - previous_cpu_ticks[0]
        idle_delta = cpu_ticks[1] - previous_cpu_ticks[1]
        if total_delta > 0:
            system_cpu_percent = 100 * (1 - idle_delta / total_delta)

    total_memory_bytes = memory[0] if memory is not None else None
    available_memory_bytes = memory[1] if memory is not None else None
    record = {
        "timestamp_utc": _utc_now(),
        "event": "sample",
        "server_pid": pid,
        "server_rss_bytes": rss_bytes,
        "server_cpu_percent_of_machine": process_cpu_percent_of_machine,
        "system_cpu_percent": system_cpu_percent,
        "system_ram_total_bytes": total_memory_bytes,
        "system_ram_available_bytes": available_memory_bytes,
    }
    output.write(json.dumps(record, separators=(",", ":")) + "\n")
    output.flush()
    return process_ticks, cpu_ticks, now


def _stop_server(server: subprocess.Popen[bytes]) -> None:
    if server.poll() is not None:
        return
    server.send_signal(signal.SIGTERM)
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve-command", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--metrics-output", type=Path, required=True)
    parser.add_argument("--server-log", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    parser.add_argument("--ready-timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()
    if args.threads <= 0:
        parser.error("--threads must be greater than zero")

    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.server_log.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "LAYA_HOST": "127.0.0.1",
            "LAYA_DEVICE": "cpu",
            "LAYA_MODELS": "english",
            "LAYA_PRELOAD": "1",
            "LAYA_THREADS": str(args.threads),
        }
    )
    started = time.monotonic()

    with args.server_log.open("ab") as server_log:
        server = subprocess.Popen(
            [str(args.serve_command)],
            env=environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            while time.monotonic() - started < args.ready_timeout_seconds:
                if server.poll() is not None:
                    return_code = server.returncode or 0
                    raise RuntimeError(
                        f"Laya server exited before readiness: {return_code}"
                    )
                if _health_is_ready(args.endpoint):
                    break
                time.sleep(0.25)
            else:
                raise TimeoutError(
                    "Laya did not become healthy before the readiness timeout."
                )

            cold_start_ms = (time.monotonic() - started) * 1000
            with args.metrics_output.open("w") as output:
                output.write(
                    json.dumps(
                        {
                            "timestamp_utc": _utc_now(),
                            "event": "ready",
                            "server_pid": server.pid,
                            "cold_start_ms": round(cold_start_ms, 3),
                            "device": "cpu",
                            "laya_threads": int(environment["LAYA_THREADS"]),
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                output.flush()
                print(
                    json.dumps(
                        {"ready": True, "cold_start_ms": round(cold_start_ms, 3)}
                    )
                )

                previous_process_ticks = None
                previous_cpu_ticks = None
                previous_sample_time = None
                while server.poll() is None:
                    (
                        previous_process_ticks,
                        previous_cpu_ticks,
                        previous_sample_time,
                    ) = _write_sample(
                        output,
                        pid=server.pid,
                        previous_process_ticks=previous_process_ticks,
                        previous_cpu_ticks=previous_cpu_ticks,
                        previous_sample_time=previous_sample_time,
                    )
                    time.sleep(max(args.sample_seconds, 0.1))
                return server.returncode or 0
        except KeyboardInterrupt:
            return 130
        finally:
            _stop_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
