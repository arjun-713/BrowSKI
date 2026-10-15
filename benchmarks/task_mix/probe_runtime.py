"""Run frozen packets against a local Laya endpoint and persist raw replies."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from browser_agent.decisions.laya import LayaProvider

from benchmarks.task_mix.probe_analysis import (
    _markdown_report,
    response_model_metadata,
    summarize,
)
from benchmarks.task_mix.probe_dataset import _sha256
from benchmarks.task_mix.probe_requests import _ask, _request_variants

REPO_ROOT = Path(__file__).resolve().parents[2]


def _health(endpoint: str, timeout: float) -> dict[str, Any]:
    request = Request(f"{endpoint}/health", method="GET")
    started = __import__("time").perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except (HTTPError, URLError, TimeoutError) as exc:
        return {
            "status": "unavailable",
            "error": type(exc).__name__,
            "elapsed_ms": round(
                (__import__("time").perf_counter() - started) * 1000, 3
            ),
        }
    return {
        "status": status,
        "elapsed_ms": round((__import__("time").perf_counter() - started) * 1000, 3),
        "response_raw": body,
        "response": _json_object(body),
    }


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


async def run_probe(
    rows: list[dict[str, Any]],
    *,
    endpoint: str,
    results_path: Path,
    summary_path: Path,
    report_path: Path,
    manifest: dict[str, Any],
) -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from benchmarks.laya.interface import (
        RecordingJsonTransport,
        live_recording_transport,
    )

    health = _health(endpoint, timeout=2.0)
    if health.get("status") != 200:
        raise RuntimeError(f"Laya loopback health check failed: {health}")
    for output_path in (results_path, summary_path, report_path):
        if output_path.exists():
            raise FileExistsError(f"preserve existing probe output: {output_path}")
    health_payload = health.get("response", {})
    recorder = RecordingJsonTransport(live_recording_transport)
    provider = LayaProvider(
        endpoint_url=endpoint,
        timeout_ms=30_000,
        health_timeout_ms=2_000,
        transport=recorder,
    )
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with results_path.open("x", encoding="utf-8") as target:
        for row in rows:
            for variant in _request_variants(row, "broad"):
                result = await _ask(provider, endpoint, row, "broad", variant)
                results.append(result)
                target.write(
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
                target.flush()
            for variant in _request_variants(row, "scoped"):
                result = await _ask(provider, endpoint, row, "scoped", variant)
                results.append(result)
                target.write(
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
                target.flush()
    manifest = {
        **manifest,
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_sha256": _sha256(results_path),
        "inference_call_count": len(results),
    }
    model_metadata = response_model_metadata(results)
    environment = {
        "endpoint": endpoint,
        **model_metadata,
        "model_revision": health_payload.get("revisions", {}).get("english"),
        "device": health_payload.get("device"),
        "health": health_payload,
    }
    summary = summarize(results, manifest)
    summary["environment"] = environment
    summary["manifest"] = manifest
    with summary_path.open("x", encoding="utf-8") as target:
        json.dump(summary, target, ensure_ascii=False, indent=2)
        target.write("\n")
    with report_path.open("x", encoding="utf-8") as target:
        target.write(
            _markdown_report(summary, manifest, environment, results_path.name)
        )
