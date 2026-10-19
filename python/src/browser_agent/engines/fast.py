"""Small provider-independent Fast task loop over Browser Use browser mechanics."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from browser_agent.engines.browser_use_runtime import is_http_url, page_evidence
from browser_agent.engines.contracts import (
    CompletionCriteria,
    EngineEvent,
    EngineResult,
    EngineStatus,
    EventSink,
    PageEvidence,
)
from browser_agent.engines.fast_browser import FastBrowser
from browser_agent.engines.fast_contract import (
    FastDecisionProvider,
    FastObservation,
    Operation,
    build_request,
)
from browser_agent.engines.lifecycle import ApprovalHandler
from browser_agent.engines.owned_tabs import TabStateChanged
from browser_agent.task_literals import TaskLiteralError

CONTROL_SETTLE_SECONDS = 0.25


class FastConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    chrome_path: str = "/usr/bin/google-chrome"
    headless: bool = True
    detailed_trace: bool = False
    max_steps: int = Field(default=12, ge=1, le=100)
    max_recoveries: int = Field(default=3, ge=0, le=5)
    timeout_seconds: int = Field(default=120, ge=5, le=600)


async def run_fast(
    goal: str,
    start_url: str,
    provider: FastDecisionProvider,
    config: FastConfig | None = None,
    *,
    criteria: CompletionCriteria | None = None,
    event_sink: EventSink | None = None,
    cancel: asyncio.Event | None = None,
    before_decision: Callable[[], Awaitable[None]] | None = None,
    approve_action: ApprovalHandler | None = None,
) -> EngineResult:
    """Bounded links, literal fields and one approved named transition, no generative calls.

    Unsupported form operations are not guessed or silently routed to a paid
    provider. Engine contracts and ownership stay the same for Laya and Jev.
    """
    from urllib.parse import urlsplit

    config = config or FastConfig()

    if not is_http_url(start_url):
        raise ValueError("Fast requires an HTTP(S) starting URL without credentials.")
    host = urlsplit(start_url).hostname
    if not host:
        raise ValueError("Fast requires an explicit HTTP(S) starting URL.")
    started = time.perf_counter()
    steps = actions = recoveries = provider_errors = 0
    retries = 0
    latencies: list[float] = []
    history: list[dict[str, str | bool | None]] = []
    evidence: PageEvidence | None = None
    status = EngineStatus.BLOCKED
    error: str | None = None
    failure_phase: str | None = None

    async def emit(
        kind: str,
        operation: str | None = None,
        target: str | None = None,
        verified: bool | None = None,
        latency_ms: float | None = None,
    ) -> None:
        await EngineEvent(
            kind=kind,
            provider=provider.name,
            model=provider.model,
            step=steps,
            operation=operation,
            candidate_id=target,
            verified=verified,
            latency_ms=latency_ms,
        ).publish(event_sink)

    async def execute() -> None:
        nonlocal evidence, status, steps, actions, recoveries, retries
        nonlocal provider_errors, error, failure_phase
        receipt_target: str | None = None

        async def observe(owned: FastBrowser) -> FastObservation:
            nonlocal recoveries, retries
            while True:
                try:
                    return await owned.observe_links({host})
                except TabStateChanged:
                    recoveries += 1
                    retries += 1
                    await emit("recovery", verified=False)
                    if retries > config.max_recoveries:
                        raise
                    await asyncio.sleep(CONTROL_SETTLE_SECONDS)

        async with FastBrowser(chrome_path=config.chrome_path, headless=config.headless) as owned:
            assert owned.browser is not None
            owned.enable_fields(goal, approve_action)
            await owned.browser.start()
            page = await owned.browser.get_current_page()
            if page is None:
                raise RuntimeError("Managed browser has no page.")
            await page.goto(start_url)
            await emit("task_started")
            for _ in range(config.max_steps):
                if before_decision is not None:
                    await before_decision()
                if cancel is not None and cancel.is_set():
                    status = EngineStatus.CANCELLED
                    break
                observation = await observe(owned)
                current_evidence = await page_evidence(owned.browser)
                evidence = current_evidence
                headings = tuple(current_evidence.headings) if current_evidence else ()
                progress_before = (owned.progress_id, headings)
                if owned.pending_click and (criteria is None or criteria.verify(evidence)):
                    failure_phase = "task"
                    error = "The named action needs outcome checks that do not already match."
                    break
                if criteria is not None and criteria.verify(evidence) and owned.completion_ready:
                    if owned.awaiting_outcome:
                        await emit("verification", Operation.CLICK, receipt_target, True)
                    status = EngineStatus.COMPLETED
                    break
                if owned.input_unavailable and not owned.completion_ready:
                    error = "Fast interactions require an approval-capable client; use the sidebar."
                    break
                if owned.awaiting_outcome:
                    await emit("verification", Operation.CLICK, receipt_target, False)
                    if retries < config.max_recoveries:
                        retries += 1
                        recoveries += 1
                        await emit("recovery", verified=False)
                        await asyncio.sleep(CONTROL_SETTLE_SECONDS)
                        continue
                    status = EngineStatus.PARTIALLY_COMPLETED
                    failure_phase = "verification"
                    error = "The approved action ran once; its requested outcome was not verified."
                    break
                if not observation.candidates:
                    if retries < config.max_recoveries:
                        retries += 1
                        recoveries += 1
                        await emit("recovery", verified=False)
                        await asyncio.sleep(CONTROL_SETTLE_SECONDS)
                        continue
                    status = EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED
                    error = "No supported links or literal-bound text fields can advance this task."
                    break
                request = build_request(
                    goal, observation, tuple(history[-10:]), allow_done=criteria is None
                )
                from browser_agent.telemetry.debug_log import record_debug

                if config.detailed_trace:
                    record_debug("fast.decision_input", request.model_dump(mode="json"), step=steps)
                try:
                    await emit("inference_started")
                    decision = await provider.predict(request)
                except Exception:
                    provider_errors += 1
                    failure_phase = "provider"
                    await emit("provider_failed")
                    raise
                if config.detailed_trace:
                    record_debug(
                        "fast.decision_result", decision.model_dump(mode="json"), step=steps
                    )
                steps += 1
                latencies.append(decision.latency_ms)
                await emit(
                    "decision",
                    decision.operation,
                    decision.candidate_id,
                    latency_ms=decision.latency_ms,
                )
                if decision.status == "failed":
                    provider_errors += 1
                    failure_phase = "provider"
                    await emit("provider_failed")
                    error = "Decision provider failed; no browser action executed."
                    break
                if decision.status == "abstained":
                    error = "Decision provider abstained; no browser action executed."
                    break
                if decision.operation in (Operation.DONE, Operation.BLOCKED):
                    status = EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED
                    error = "Model stopped without independent evidence for the requested outcome."
                    break
                if (
                    decision.operation is None
                    or decision.operation
                    not in {Operation.CLICK, Operation.TYPE_TEXT, Operation.SELECT}
                    or decision.candidate_id is None
                ):
                    error = "The selected operation is unsupported by this Fast action vocabulary."
                    break
                selected = next(
                    (c for c in observation.candidates if c.id == decision.candidate_id), None
                )
                if (
                    decision.observation_id != observation.id
                    or selected is None
                    or selected.operation is not decision.operation
                ):
                    provider_errors += 1
                    failure_phase = "provider"
                    error = "The decision does not match its observed operation and target."
                    await emit("provider_failed", decision.operation, decision.candidate_id, False)
                    break
                fresh = await observe(owned)
                if fresh.id != decision.observation_id:
                    recoveries += 1
                    retries += 1
                    await emit("recovery", verified=False)
                    if retries > config.max_recoveries:
                        status = (
                            EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED
                        )
                        error = "Page kept changing before execution; recovery budget exhausted."
                        break
                    continue
                failure_phase = "browser"
                if owned.requires_approval(decision.candidate_id):
                    outcome = await owned.execute_observed(
                        decision.candidate_id, decision.operation
                    )
                    if outcome.reacquired:
                        recoveries += 1
                        await emit(
                            "recovery", decision.operation, decision.candidate_id, outcome.verified
                        )
                    if outcome.verified is False:
                        actions += int(outcome.invoked)
                        failure_phase = owned.action_failure_phase
                        error = (
                            owned.input_blocked_reason or "The approved browser operation failed."
                        )
                        event_kind = "browser_failed"
                        if failure_phase == "approval":
                            event_kind = "approval_blocked"
                        elif failure_phase == "verification":
                            event_kind = "verification"
                        await emit(
                            event_kind,
                            decision.operation,
                            decision.candidate_id,
                            False,
                        )
                        break
                    if decision.operation is Operation.CLICK:
                        receipt_target = decision.candidate_id
                else:
                    try:
                        await owned.click_observed(decision.candidate_id)
                    except TabStateChanged as changed:
                        actions += int(changed.invoked)
                        recoveries += 1
                        retries += 1
                        await emit("recovery", decision.operation, decision.candidate_id, False)
                        if retries > config.max_recoveries:
                            status = (
                                EngineStatus.PARTIALLY_COMPLETED
                                if actions
                                else EngineStatus.BLOCKED
                            )
                            error = "Owned tab changes exhausted the recovery budget."
                            break
                        continue
                    if selected.role == "tab":
                        await emit("tab_selected", decision.operation, decision.candidate_id, True)
                actions += 1
                await emit("action_finished", decision.operation, decision.candidate_id)
                failure_phase = "verification"
                # Fresh DOM/AX collection also waits for the navigation watchdog.
                await observe(owned)
                current_evidence = await page_evidence(owned.browser)
                evidence = current_evidence
                headings = tuple(current_evidence.headings) if current_evidence else ()
                progressed = (owned.progress_id, headings) != progress_before
                failure_phase = None
                action_verified = progressed
                if owned.awaiting_outcome:
                    action_verified = criteria is not None and criteria.verify(evidence)
                await emit(
                    "verification", decision.operation, decision.candidate_id, action_verified
                )
                history.append(
                    {
                        "action": next(
                            c.label for c in observation.candidates if c.id == decision.candidate_id
                        ),
                        "kind": "select_tab"
                        if selected.role == "tab"
                        else decision.operation.value.lower(),
                        "text": None,
                        "page_changed": progressed,
                    }
                )
                history[:] = history[-10:]
                if criteria is not None and criteria.verify(evidence) and owned.completion_ready:
                    status = EngineStatus.COMPLETED
                    break
                if not progressed:
                    recoveries += 1
                    retries += 1
                    await emit("recovery", decision.operation, decision.candidate_id, False)
                    if retries > config.max_recoveries:
                        error = "Repeated unverified actions exhausted the recovery budget."
                        break
            else:
                status = EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED
                error = "Fast decision step budget exhausted."

    work: asyncio.Task[None] | None = None
    watch: asyncio.Task[bool] | None = None
    try:
        work = asyncio.create_task(execute())
        if cancel is not None:
            watch = asyncio.create_task(cancel.wait())
        pending: set[asyncio.Task[None] | asyncio.Task[bool]] = {work}
        if watch is not None:
            pending.add(watch)
        finished, _ = await asyncio.wait(
            pending, timeout=config.timeout_seconds, return_when=asyncio.FIRST_COMPLETED
        )
        if cancel is not None and cancel.is_set():
            status = EngineStatus.CANCELLED
        elif work in finished:
            await work
        elif watch is not None and watch in finished:
            status = EngineStatus.CANCELLED
        else:
            status = EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED
            error = "Fast task time budget exhausted."
    except asyncio.CancelledError:
        raise
    except TaskLiteralError as exc:
        status = EngineStatus.BLOCKED
        failure_phase = "task"
        error = str(exc)
    except TabStateChanged:
        status = EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED
        failure_phase = "browser"
        error = "Owned tab changes exhausted the recovery budget."
        await emit("browser_failed")
    except Exception as exc:
        status = EngineStatus.FAILED
        failure_phase = "provider" if provider_errors else "browser"
        if not provider_errors:
            await emit("browser_failed")
        error = f"Fast {failure_phase} failed ({type(exc).__name__})."
    finally:
        for task in (work, watch):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await provider.aclose()
        await emit("task_finished", verified=EngineStatus(status) is EngineStatus.COMPLETED)
    return EngineResult(
        status=status,
        provider=provider.name,
        model=provider.model,
        evidence=evidence,
        answer=evidence.headings[0] if evidence and evidence.headings else None,
        verified=EngineStatus(status) is EngineStatus.COMPLETED,
        steps=steps,
        action_count=actions,
        provider_errors=provider_errors,
        recovery_count=recoveries,
        decision_latencies_ms=latencies,
        duration_ms=(time.perf_counter() - started) * 1000,
        failure_phase=failure_phase,
        error=error,
    )
