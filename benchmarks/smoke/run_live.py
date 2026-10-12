"""Opt-in live Luna smoke runner for local synthetic browser workflows."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import perf_counter
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "python" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT))

from browser_agent._types import SemanticElement, SemanticSnapshot, VisibilityClass
from browser_agent.agent import AgentConfig, AgentRuntime, LunaDecisionAgent
from browser_agent.agent.events import RuntimeEvent
from browser_agent.cli.config import BrowskiConfig
from browser_agent.cli.main import _create_luna_reasoning_provider, _load_runtime_config
from browser_agent.credentials import configured_openai_api_key
from browser_agent.session import BrowserSession
from browser_agent.telemetry.debug_log import DebugLogConfig

from benchmarks.smoke.measurements import read_event_metrics
from benchmarks.smoke.scenarios import SmokeCase, cases

FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "smoke"
ROUTES = {
    "/short": "short-picker.html",
    "/registration": "medium-preferences.html",
    "/shop": "long-shopping-catalog.html",
    "/product/studio-14": "long-shopping-product.html",
    "/product/studio-16": "long-shopping-product.html",
    "/product/travel-13": "long-shopping-product.html",
    "/shortlist": "long-shopping-shortlist.html",
}


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        fixture_name = ROUTES.get(self.path)
        if fixture_name is None:
            self.send_error(404)
            return
        body = (FIXTURES / fixture_name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


def serve_fixtures() -> tuple[ThreadingHTTPServer, Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def _element_in_viewport(element: SemanticElement, snapshot: SemanticSnapshot) -> bool:
    bbox = element.bbox
    viewport = snapshot.viewport
    return (
        element.visible
        and element.visibility == VisibilityClass.VISIBLE
        and bbox is not None
        and bbox.width > 0
        and bbox.height > 0
        and bbox.x < viewport.width
        and bbox.y < viewport.height
        and bbox.x + bbox.width > 0
        and bbox.y + bbox.height > 0
    )


def visible_snapshot_text(snapshot: SemanticSnapshot) -> str:
    values: list[str] = []
    for element in snapshot.elements:
        if not _element_in_viewport(element, snapshot):
            continue
        values.extend((element.text or "", element.accessible_name or ""))
    return "\n".join(values)


async def _run_case(
    case: SmokeCase,
    base_url: str,
    config: BrowskiConfig,
    artifact_dir: Path,
) -> dict[str, object]:
    run_id = f"live-smoke-{case.name}-{uuid4().hex[:8]}"

    async def record_event(event: RuntimeEvent) -> None:
        _ = event

    reasoning = _create_luna_reasoning_provider(config)
    if reasoning is None:
        raise RuntimeError("Luna reasoning is disabled in the active configuration.")

    debug = DebugLogConfig(
        enabled=True,
        directory=artifact_dir / "events",
        max_session_bytes=8 * 1024 * 1024,
        max_sessions=20,
        retention_days=30,
    )
    active_config = replace(config, debug=debug)
    started = perf_counter()
    async with BrowserSession.launch(
        headless=True,
        browser_code_enabled=active_config.browser_code.enabled,
    ) as browser:
        await browser.navigate(f"{base_url}{case.start_path}")
        agent = LunaDecisionAgent(
            decision_provider=None,
            reasoning_provider=reasoning,
            model=active_config.reasoning.model,
            browser_code_enabled=active_config.browser_code.enabled,
            default_effort=active_config.reasoning.effort,
            site_aliases=active_config.site_aliases,
        )
        runtime_config = AgentConfig(
            max_steps=case.max_steps,
            max_llm_calls=case.max_llm_calls,
            max_stagnant_steps=4,
            max_recovery_actions=3,
            max_replans=1,
            confirm_high_risk=True,
        )
        async with AgentRuntime.open_sqlite(
            agent,
            browser,
            database=artifact_dir / "checkpoints.sqlite",
            config=runtime_config,
            event_sink=record_event,
            debug_config=active_config.debug,
        ) as runtime:
            result = await runtime.run(case.prompt, run_id=run_id)
        snapshot = await browser.observe()
        tab_details = await browser.tabs()

    visible_text = visible_snapshot_text(snapshot)
    evidence_found = case.expected_visible_text in visible_text
    element_values = {
        element.ref: element.value or element.text or ""
        for element in snapshot.elements
        if _element_in_viewport(element, snapshot)
    }
    expected_values_found = all(
        element_values.get(ref) == expected
        for ref, expected in case.expected_element_values
    )
    tab_urls = [tab.url for tab in tab_details]
    expected_tabs_found = set(case.expected_tab_urls).issubset(tab_urls)
    tabs_opened = len(tab_details)
    event_path = artifact_dir / "events" / run_id / "events.jsonl"
    provider_metrics = read_event_metrics(event_path)
    raw_call_count_value = provider_metrics["provider_call_count"]
    raw_call_count = (
        raw_call_count_value if isinstance(raw_call_count_value, int) else 0
    )
    status_ok = result.status == "completed" and result.done
    bounds_ok = (
        result.steps_taken <= case.max_steps and result.llm_calls <= case.max_llm_calls
    )
    raw_call_bound_ok = raw_call_count <= case.max_llm_calls
    case_passed = (
        status_ok
        and bounds_ok
        and raw_call_bound_ok
        and evidence_found
        and expected_values_found
        and expected_tabs_found
        and tabs_opened >= case.minimum_tabs
    )
    snapshot_path = artifact_dir / f"{case.name}.final-snapshot.json"
    snapshot_data = snapshot.model_dump(mode="json")
    snapshot_path.write_text(
        json.dumps(snapshot_data, indent=2) + "\n",
        encoding="utf-8",
    )
    record = {
        "case": case.name,
        "run_id": run_id,
        "model": active_config.reasoning.model,
        "reasoning_effort": active_config.reasoning.effort.value,
        "status": result.status,
        "done": result.done,
        "steps": result.steps_taken,
        "step_budget": case.max_steps,
        "llm_calls": result.llm_calls,
        "llm_call_budget": case.max_llm_calls,
        "raw_provider_calls": raw_call_count,
        "raw_provider_call_budget_ok": raw_call_bound_ok,
        "time_budget_seconds": case.max_seconds,
        "elapsed_seconds": round(perf_counter() - started, 3),
        "provider_metrics": provider_metrics,
        "tabs_opened": tabs_opened,
        "tab_urls": tab_urls,
        "expected_visible_text": case.expected_visible_text,
        "evidence_found": evidence_found,
        "expected_element_values": dict(case.expected_element_values),
        "element_values_found": expected_values_found,
        "expected_tab_urls": list(case.expected_tab_urls),
        "expected_tabs_found": expected_tabs_found,
        "final_snapshot": str(snapshot_path),
        "result_summary": result.result_summary,
        "debug_events": str(event_path),
        "passed": case_passed,
    }
    (artifact_dir / f"{case.name}.json").write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


async def run_live(
    config_path: Path | None, selected_cases: set[str], artifact_dir: Path
) -> int:
    config = _load_runtime_config(config_path)
    if config.reasoning.provider != "openai" or not config.reasoning.enabled:
        raise RuntimeError(
            "Configure the existing OpenAI Luna provider before running smoke tasks."
        )
    if configured_openai_api_key() is None:
        raise RuntimeError("No existing OpenAI credential is configured for Luna.")

    server, thread, base_url = serve_fixtures()
    results: list[dict[str, object]] = []
    started_at = datetime.now(UTC).isoformat()
    try:
        available_cases = cases(base_url)
        unknown_cases = selected_cases - {case.name for case in available_cases}
        if unknown_cases:
            raise ValueError(
                f"Unknown smoke case names: {', '.join(sorted(unknown_cases))}"
            )
        manifest = {
            "started_at": started_at,
            "model": config.reasoning.model,
            "reasoning_effort": config.reasoning.effort.value,
            "cases": [
                {
                    "name": case.name,
                    "start_path": case.start_path,
                    "prompt": case.prompt,
                    "expected_visible_text": case.expected_visible_text,
                    "expected_element_values": list(case.expected_element_values),
                    "expected_tab_urls": list(case.expected_tab_urls),
                    "max_steps": case.max_steps,
                    "max_llm_calls": case.max_llm_calls,
                    "max_seconds": case.max_seconds,
                }
                for case in available_cases
                if not selected_cases or case.name in selected_cases
            ],
        }
        manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        (artifact_dir / "case-manifest.json").write_bytes(manifest_bytes)
        (artifact_dir / "case-manifest.sha256").write_text(
            f"{hashlib.sha256(manifest_bytes).hexdigest()}  case-manifest.json\n",
            encoding="utf-8",
        )
        for case in available_cases:
            if selected_cases and case.name not in selected_cases:
                continue
            try:
                result = await asyncio.wait_for(
                    _run_case(case, base_url, config, artifact_dir),
                    timeout=case.max_seconds,
                )
            except TimeoutError:
                result = {
                    "case": case.name,
                    "status": "timeout",
                    "passed": False,
                    "max_seconds": case.max_seconds,
                }
            results.append(result)
            print(json.dumps(result, sort_keys=True))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    summary = {
        "model": config.reasoning.model,
        "reasoning_effort": config.reasoning.effort.value,
        "started_at": started_at,
        "cases": results,
        "passed": bool(results) and all(bool(item.get("passed")) for item in results),
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if summary["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, help="Reuse an existing BROWSKI TOML config."
    )
    parser.add_argument(
        "--case", action="append", default=[], help="Select a smoke case by name."
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=REPOSITORY_ROOT / "debug-logs" / "live-task-smoke",
        help="Ignored local directory for raw debug logs and measurements.",
    )
    parser.add_argument(
        "--confirm-live-api",
        action="store_true",
        help="Explicitly opt in to live Luna API calls and associated usage charges.",
    )
    args = parser.parse_args()
    if not args.confirm_live_api:
        parser.error("pass --confirm-live-api to run live model-backed tasks")
    if args.artifacts.exists() and not args.artifacts.is_dir():
        parser.error("--artifacts must point to a directory")
    args.artifacts.mkdir(parents=True, exist_ok=True)
    return asyncio.run(run_live(args.config, set(args.case), args.artifacts))


if __name__ == "__main__":
    raise SystemExit(main())
