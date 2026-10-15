"""Run one frozen task-mix suite variant through the Rust browser runtime."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.task_mix.budgets import ExecutionPolicy
from benchmarks.task_mix.dataset import DEFAULT_SEED, load_case_file, load_cases
from benchmarks.task_mix.evaluate import (
    FixtureStateServer,
    evaluate_case,
    write_summary_csv,
)
from benchmarks.task_mix.metrics import EventTally, RuntimeTally, build_manifest
from benchmarks.task_mix.resume import (
    append_resume_manifest,
    reconstruct_aggregate,
    validate_resume,
)


def _ordered_cases(suite: str, seed: int) -> list[Any]:
    names = (
        ["development", "holdout"]
        if suite == "all"
        else ["development" if suite == "dev" else suite]
    )
    cases = [case for name in names for case in load_cases(name)]
    random.Random(seed).shuffle(cases)
    return cases


def _write_json_line(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _capture_debug_counts(
    source: Path, destination: Path, case_id: str, case_run_id: str
) -> dict[str, int]:
    counts = Counter()
    for log in source.glob("*/events.jsonl"):
        try:
            rows = [
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
            ]
        except (OSError, json.JSONDecodeError):
            continue
        for row in rows:
            event = str(row.get("event", ""))
            if row.get("run_id") != case_run_id:
                continue
            if event.startswith("provider."):
                _write_json_line(destination, {"case_id": case_id, **row})
                counts["provider_debug_records"] += 1
            if event == "decision.local_route":
                counts["local_route_events"] += 1
                outcome = row.get("payload", {}).get("outcome")
                if outcome in {"accepted", "fallback"}:
                    counts[f"local_route_{outcome}"] += 1
    return dict(counts)


async def _run(args: argparse.Namespace) -> int:
    if args.resume and args.source_root is None:
        prior_manifest_path = args.resume.expanduser() / "manifest.json"
        try:
            prior_manifest = json.loads(prior_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"cannot read resume manifest {prior_manifest_path}: {exc}"
            ) from exc
        recorded_source_root = prior_manifest.get("source_root")
        if not isinstance(recorded_source_root, str) or not recorded_source_root:
            raise ValueError(
                "resume manifest has no source_root; provide --source-root explicitly"
            )
        args.source_root = Path(recorded_source_root)
    if args.source_root:
        root = Path(args.source_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"source root does not exist: {root}")
        import_root = root.parent if root.name == "browser_agent" else root
        sys.path.insert(0, str(import_root))
    policy = ExecutionPolicy(
        budget_scale=args.budget_scale,
        difficulty=args.difficulty,
        max_steps=args.max_steps,
        max_luna_calls=args.max_luna_calls,
        max_case_seconds=args.max_case_seconds,
    )
    if args.corpus:
        source_cases = list(load_case_file(args.corpus))
        random.Random(args.seed).shuffle(source_cases)
    else:
        source_cases = _ordered_cases(args.suite, args.seed)
    cases = [
        case
        for case in source_cases
        if policy.difficulty == "all" or case.difficulty == policy.difficulty
    ]
    if args.resume:
        output = args.resume.expanduser().resolve()
        run_id = output.name
        start_order = 0
    else:
        run_id = f"{args.variant}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        output = args.output.expanduser().resolve() / run_id
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
        os.chmod(output, 0o700)
        debug_root = output / "debug"
        debug_root.mkdir(mode=0o700)
        start_order = 0
    results_path = output / "results.jsonl"
    provider_debug_path = output / "provider-debug.jsonl"
    summary_path = output / "summary.json"
    server = FixtureStateServer()
    thread = threading.Thread(
        target=server.serve_forever, name="task-mix-fixtures", daemon=True
    )
    thread.start()
    try:
        manifest = build_manifest(
            cases,
            args.suite,
            args.variant,
            args.seed,
            server.base_url,
            source_root=args.source_root,
        )
        manifest["execution_policy"] = policy.describe()
        manifest["bounds"]["max_case_seconds"] = policy.seconds_cap
        if args.corpus:
            manifest["corpus_path"] = str(args.corpus.resolve())
            manifest["source_sha256"] = hashlib.sha256(
                args.corpus.read_bytes()
            ).hexdigest()
        if args.resume:
            initial_manifest_path = output / "manifest.json"
            initial_manifest = json.loads(
                initial_manifest_path.read_text(encoding="utf-8")
            )
            resume_state = validate_resume(output, manifest)
            run_id = resume_state.run_id
            start_order = resume_state.next_order
            debug_root = output / "debug"
            append_resume_manifest(output, initial_manifest, manifest, start_order)
        else:
            (output / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        # Imports happen after source-root insertion so baseline runs use their frozen package.
        from browser_agent.agent.luna import LunaDecisionAgent
        from browser_agent.agent.runtime import AgentConfig, AgentRuntime
        from browser_agent.cli.config import load_config
        from browser_agent.credentials import (
            configured_openai_api_key,
            load_local_env_credentials,
        )
        from browser_agent.providers.privacy import PrivacyMode, ProviderBoundary
        from browser_agent.reasoning import OpenAILunaProvider
        from browser_agent.session import BrowserSession
        from browser_agent.telemetry.debug_log import DebugLogConfig

        load_local_env_credentials(Path(__file__).resolve().parents[2] / ".env")
        config = load_config(args.config)
        for order, case in enumerate(cases[start_order:], start=start_order):
            server.activate_case(case.case_id)
            startup_started = time.perf_counter()
            event_tally = EventTally()
            runtime_tally = RuntimeTally()
            error: str | None = None
            result: Any = None
            tabs: list[Any] = []
            active_url: str | None = None
            case_run_id = uuid.uuid4().hex
            reasoning = ProviderBoundary(
                OpenAILunaProvider(
                    api_key=configured_openai_api_key(),
                    telemetry=event_tally,
                ),
                mode=PrivacyMode(config.privacy.mode.value),
            )
            agent_args: dict[str, Any] = {
                "decision_provider": None,
                "reasoning_provider": reasoning,
            }
            if args.variant == "prefer-laya":
                from browser_agent.decisions.fast_path import LayaRoutingPolicy
                from browser_agent.decisions.laya import LayaProvider

                if not args.routing_policy:
                    raise ValueError("--routing-policy is required for prefer-laya")
                routing_policy = LayaRoutingPolicy.load(args.routing_policy)
                agent_args["decision_provider"] = LayaProvider(
                    endpoint_url=args.laya_endpoint,
                    telemetry=event_tally,
                )
                agent_args["laya_routing_policy"] = routing_policy
            agent = LunaDecisionAgent(**agent_args)
            debug_config = DebugLogConfig(enabled=True, directory=debug_root)
            try:
                async with BrowserSession.launch(headless=True) as browser:
                    startup_ms = (time.perf_counter() - startup_started) * 1000
                    started = time.perf_counter()
                    case_with_url = case.with_base_url(server.base_url)
                    url = f"{case_with_url['start_url']}?benchmark_case={case.case_id}"
                    max_steps, max_calls, case_timeout = policy.case_limits(case)
                    try:
                        await asyncio.wait_for(
                            browser.navigate(url), timeout=case_timeout
                        )
                    except TimeoutError:
                        error = "case_timeout"
                    if error != "case_timeout":
                        runtime = AgentRuntime(
                            agent,
                            browser,
                            AgentConfig(
                                max_steps=max_steps,
                                max_llm_calls=max_calls,
                                confirm_high_risk=True,
                            ),
                            event_sink=runtime_tally,
                            debug_config=debug_config,
                        )
                        remaining = max(
                            0.001,
                            case_timeout - (time.perf_counter() - started),
                        )
                        try:
                            result = await asyncio.wait_for(
                                runtime.run(case_with_url["task"], run_id=case_run_id),
                                timeout=remaining,
                            )
                        except TimeoutError:
                            error = "case_timeout"
                        except Exception as exc:  # noqa: BLE001 - capture case failures and continue the suite.
                            error = f"{type(exc).__name__}: {str(exc)[:300]}"
                    latency_ms = (time.perf_counter() - started) * 1000
                    try:
                        tabs = await browser.tabs()
                        active_tab_id = await browser.active_tab_id()
                        active_url = next(
                            (tab.url for tab in tabs if tab.id == active_tab_id),
                            None,
                        )
                    except Exception as exc:  # noqa: BLE001 - tab evidence failure is per-case.
                        error = error or f"tab_read:{type(exc).__name__}"
            except Exception as exc:  # noqa: BLE001 - browser startup failure is a case result.
                startup_ms = (time.perf_counter() - startup_started) * 1000
                latency_ms = 0.0
                error = error or f"browser:{type(exc).__name__}: {str(exc)[:300]}"
            await asyncio.sleep(0.15)
            with server.state_lock:
                observed_state = server.states.get(case.case_id)
            result_status = getattr(result, "status", "failed") if result else "failed"
            tab_urls = [getattr(tab, "url", "") for tab in tabs]
            evaluation = evaluate_case(
                case.with_base_url(server.base_url),
                observed_state,
                runtime_status=result_status,
                tab_urls=tab_urls,
                active_url=active_url,
            )
            debug_counts = _capture_debug_counts(
                debug_root, provider_debug_path, case.case_id, case_run_id
            )
            provider_debug_count = debug_counts.get("provider_debug_records", 0)
            provider_summary = event_tally.summary()
            runtime_counts = runtime_tally.counts()
            operations = provider_summary["provider_operation_events"]
            luna_calls = sum(
                count
                for key, count in operations.items()
                if key.startswith(("openai:reason", "openai:vision"))
            )
            record = {
                "case_id": case.case_id,
                "split": case.split,
                "difficulty": case.difficulty,
                "variant": args.variant,
                "run_id": run_id,
                "case_run_id": case_run_id,
                "order": order,
                "runtime_status": result_status,
                "success": evaluation["success"],
                "evaluation": evaluation,
                "startup_ms": round(startup_ms, 2),
                "latency_ms": round(latency_ms, 2),
                "steps_taken": getattr(result, "steps_taken", 0),
                "actions_completed": runtime_tally.count("ActionCompleted"),
                "luna_calls": luna_calls,
                "laya_calls": sum(
                    count for key, count in operations.items() if key == "laya:evaluate"
                ),
                "laya_accept_count": debug_counts.get("local_route_accepted", 0),
                "laya_fallback_count": debug_counts.get("local_route_fallback", 0),
                "escalation_count": sum(
                    "fallback" in str(event.get("operation", "")).casefold()
                    or event.get("fallback_to") is not None
                    for event in event_tally.events
                )
                if not debug_counts.get("local_route_events")
                else debug_counts.get("local_route_fallback", 0),
                "provider_metrics": provider_summary,
                "provider_events": event_tally.events,
                "runtime_event_counts": runtime_counts,
                "provider_debug_records": provider_debug_count,
                "errors": ([error] if error else [])
                + (
                    ["runtime_failed"]
                    if result_status == "failed" and not error
                    else []
                )
                + [
                    event["error_type"]
                    for event in event_tally.events
                    if event.get("error_type")
                ],
                "active_url": active_url,
                "tab_urls": tab_urls,
                "observed_evaluator_state": observed_state,
            }
            _write_json_line(results_path, record)
            print(
                f"[{order + 1}/{len(cases)}] {case.case_id}: "
                f"{'PASS' if evaluation['success'] else 'FAIL'} ({result_status})"
            )
        result_rows = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
        ]
        aggregate = reconstruct_aggregate(
            run_id,
            args.suite,
            args.variant,
            result_rows,
            len(cases),
        )
        summary_path.write_text(
            json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_summary_csv(output / "summary.csv", result_rows)
        print(f"Results: {output}")
        return 0 if aggregate["successes"] == len(cases) else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("dev", "holdout", "all"), default="dev")
    parser.add_argument(
        "--variant", choices=("baseline", "optimized", "prefer-laya"), required=True
    )
    parser.add_argument(
        "--source-root", type=Path, help="Python source root for a frozen baseline"
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--corpus", type=Path, help="explicit separately frozen JSONL corpus"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/task-mix"))
    parser.add_argument(
        "--resume", type=Path, help="continue an interrupted task-mix run directory"
    )
    parser.add_argument("--routing-policy", type=Path)
    parser.add_argument("--laya-endpoint", default="http://127.0.0.1:8001")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-steps", type=int, default=120)
    parser.add_argument("--max-luna-calls", type=int, default=30)
    parser.add_argument("--max-case-seconds", type=int)
    parser.add_argument("--budget-scale", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument(
        "--difficulty", choices=("all", "small", "medium", "large"), default="all"
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.max_steps < 1 or args.max_luna_calls < 1:
        raise SystemExit("max steps and Luna calls must be positive")
    if args.variant == "baseline" and args.source_root is None:
        raise SystemExit(
            "baseline runs require --source-root pointing to the frozen package"
        )
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
