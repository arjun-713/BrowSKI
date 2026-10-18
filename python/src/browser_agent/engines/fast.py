"""Small provider-independent Fast task loop over Browser Use browser mechanics."""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel, ConfigDict, Field

from browser_agent.engines.browser_use_runtime import page_evidence
from browser_agent.engines.contracts import (
    CompletionCriteria,
    EngineEvent,
    EngineResult,
    EngineStatus,
    EventSink,
    PageEvidence,
)
from browser_agent.engines.fast_browser import FastBrowser
from browser_agent.engines.fast_contract import FastDecisionProvider, Operation, build_request


class FastConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    chrome_path: str = "/usr/bin/google-chrome"
    headless: bool = True
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
) -> EngineResult:
    """Initial supported slice: same-site link navigation, no generative calls.

    Unsupported text/form actions are not guessed or silently routed to a paid
    provider. Engine contracts and ownership stay the same for Laya and Jev.
    """
    from urllib.parse import urlsplit

    config = config or FastConfig()

    host = urlsplit(start_url).hostname
    if not host or urlsplit(start_url).scheme not in {"http", "https"}:
        raise ValueError("Fast requires an explicit HTTP(S) starting URL.")
    started = time.perf_counter()
    steps = actions = recoveries = provider_errors = 0
    latencies: list[float] = []
    history: list[dict[str, str | bool | None]] = []
    evidence: PageEvidence | None = None
    status = EngineStatus.BLOCKED
    error: str | None = None

    async def emit(
        kind: str,
        operation: str | None = None,
        target: str | None = None,
        verified: bool | None = None,
        latency_ms: float | None = None,
    ) -> None:
        if event_sink is not None:
            await event_sink(
                EngineEvent(
                    kind=kind,
                    provider=provider.name,
                    step=steps,
                    operation=operation,
                    candidate_id=target,
                    verified=verified,
                    latency_ms=latency_ms,
                )
            )

    async def execute() -> None:
        nonlocal evidence, status, steps, actions, recoveries, provider_errors, error
        async with FastBrowser(chrome_path=config.chrome_path, headless=config.headless) as owned:
            assert owned.browser is not None
            await owned.browser.start()
            page = await owned.browser.get_current_page()
            if page is None:
                raise RuntimeError("Managed browser has no page.")
            await page.goto(start_url)
            await emit("task_started")
            for _ in range(config.max_steps):
                if cancel is not None and cancel.is_set():
                    status = EngineStatus.CANCELLED
                    break
                observation = await owned.observe_links({host})
                evidence = await page_evidence(owned.browser)
                if criteria is not None and criteria.verify(evidence):
                    status = EngineStatus.COMPLETED
                    break
                request = build_request(
                    goal, observation, tuple(history[-10:]), allow_done=criteria is None
                )
                try:
                    decision = await provider.predict(request)
                except Exception:
                    provider_errors += 1
                    raise
                steps += 1
                latencies.append(decision.latency_ms)
                await emit(
                    "decision",
                    decision.operation,
                    decision.candidate_id,
                    latency_ms=decision.latency_ms,
                )
                if decision.status == "failed":
                    error = "Decision provider failed; no browser action executed."
                    break
                if decision.operation in (Operation.DONE, Operation.BLOCKED):
                    status = EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED
                    error = "Model stopped without independent evidence for the requested outcome."
                    break
                if decision.operation is not Operation.CLICK or decision.candidate_id is None:
                    error = "The selected operation is unsupported by this navigation slice."
                    break
                fresh = await owned.observe_links({host})
                if fresh.id != decision.observation_id:
                    recoveries += 1
                    await emit("recovery", verified=False)
                    if recoveries > config.max_recoveries:
                        error = "Page kept changing before execution; recovery budget exhausted."
                        break
                    continue
                await owned.click_observed(decision.candidate_id)
                actions += 1
                # Fresh DOM/AX collection also waits for the navigation watchdog.
                after = await owned.observe_links({host})
                evidence = await page_evidence(owned.browser)
                progressed = after.id != observation.id
                await emit("verification", decision.operation, decision.candidate_id, progressed)
                history.append(
                    {
                        "action": next(
                            c.label for c in observation.candidates if c.id == decision.candidate_id
                        ),
                        "kind": "click",
                        "text": None,
                        "page_changed": progressed,
                    }
                )
                history[:] = history[-10:]
                if criteria is not None and criteria.verify(evidence):
                    status = EngineStatus.COMPLETED
                    break
                if not progressed:
                    recoveries += 1
                    if recoveries > config.max_recoveries:
                        error = "Repeated unverified actions exhausted the recovery budget."
                        break
            else:
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
        if work in finished:
            await work
        elif watch is not None and watch in finished:
            status = EngineStatus.CANCELLED
        else:
            error = "Fast task time budget exhausted."
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        status = EngineStatus.FAILED
        error = f"Fast engine failed ({type(exc).__name__})."
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
        error=error,
    )
