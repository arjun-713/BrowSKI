"""Official Browser Use Agent; hosted inference only through explicit bounded opt-in."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field

from browser_agent.engines.browser_use_runtime import ManagedBrowser, page_evidence
from browser_agent.engines.contracts import (
    CompletionCriteria,
    EngineEvent,
    EngineResult,
    EngineStatus,
    EventSink,
    PageEvidence,
)
from browser_agent.engines.general_tools import InteractionPolicy
from browser_agent.engines.general_tools import navigation_tools as _navigation_tools
from browser_agent.engines.lifecycle import ApprovalHandler

if TYPE_CHECKING:
    from browser_use.agent.service import Agent
    from browser_use.agent.views import AgentHistoryList


class _InferenceTransport(httpx.AsyncBaseTransport):
    """Measure HTTP inference separately from browser/library errors."""

    def __init__(
        self, inner: httpx.AsyncBaseTransport, finished: Callable[[float, bool], Awaitable[None]]
    ) -> None:
        self._inner = inner
        self._finished = finished

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
            await response.aread()
        except Exception:
            await self._finished((time.perf_counter() - started) * 1000, True)
            raise
        await self._finished((time.perf_counter() - started) * 1000, response.status_code >= 300)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class GeneralConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model: str = "gpt-6-luna"
    allow_paid_api: bool = False
    max_calls: int = Field(default=4, ge=1, le=10)
    max_steps: int = Field(default=5, ge=1, le=20)
    timeout_seconds: int = Field(default=90, ge=5, le=300)
    chrome_path: str = "/usr/bin/google-chrome"
    headless: bool = True


async def run_general(
    goal: str,
    config: GeneralConfig,
    *,
    api_key: str | None = None,
    criteria: CompletionCriteria | None = None,
    event_sink: EventSink | None = None,
    cancel: asyncio.Event | None = None,
    model_transport: httpx.AsyncBaseTransport | None = None,
    before_decision: Callable[[], Awaitable[None]] | None = None,
    approve_action: ApprovalHandler | None = None,
) -> EngineResult:
    """Bounded Agent with optional approved interactions and independent outcome checks."""
    if not config.allow_paid_api:
        raise ValueError(
            "General needs a generative model; OpenAI requires explicit paid API opt-in."
        )
    if not api_key:
        raise ValueError("OpenAI credentials are unavailable; no hosted request was made.")
    if not goal.strip():
        raise ValueError("Task goal must not be empty.")

    started = time.perf_counter()
    calls = 0
    steps = 0
    actions = 0
    recoveries = 0
    provider_errors = 0
    answer: str | None = None
    evidence: PageEvidence | None = None
    status = EngineStatus.PARTIALLY_COMPLETED
    error: str | None = None
    failure_phase: str | None = None
    latencies: list[float] = []
    policy = InteractionPolicy(goal=goal, approve=approve_action)

    async def emit(
        kind: str,
        operation: str | None = None,
        verified: bool | None = None,
        latency_ms: float | None = None,
    ) -> None:
        await EngineEvent(
            kind=kind,
            engine="general",
            provider="openai",
            model=config.model,
            step=steps,
            operation=operation,
            verified=verified,
            latency_ms=latency_ms,
        ).publish(event_sink)

    async def inference_finished(latency: float, failed: bool) -> None:
        nonlocal provider_errors, failure_phase
        latencies.append(latency)
        if failed:
            provider_errors += 1
            failure_phase = "provider"
        await emit("provider_failed" if failed else "inference_finished", latency_ms=latency)

    async def request_guard(request: httpx.Request) -> None:
        nonlocal calls
        if request.url.host != "api.openai.com" or request.url.scheme != "https":
            raise RuntimeError("Blocked unexpected inference destination.")
        if calls >= config.max_calls:
            raise RuntimeError("Explicit hosted inference call budget exhausted.")
        calls += 1
        await emit("inference_started")

    async def after_step(agent: Agent[Any, Any]) -> None:
        nonlocal steps, evidence, actions, recoveries, provider_errors, failure_phase
        steps += 1
        evidence = await page_evidence(agent.browser_session)
        history = cast("AgentHistoryList[Any]", cast(Any, agent).history)
        if history.history:
            last = history.history[-1]
            failed = any(result.error for result in last.result)
            if last.model_output:
                if failed:
                    failure_phase = policy.blocked_phase if policy.blocked_reason else "browser"
                for index, action in enumerate(last.model_output.action):
                    operation = next(iter(action.model_dump(exclude_none=True)), "unknown")
                    metadata = (
                        cast(dict[str, object] | None, cast(Any, last.result[index]).metadata)
                        if index < len(last.result)
                        else None
                    )
                    executed = (metadata or {}).get("browski_executed", True) is not False
                    if (metadata or {}).get("browski_reacquired") is True:
                        recoveries += 1
                        await emit("recovery", operation=operation, verified=not failed)
                    actions += int(operation != "done" and executed)
                    kind = "action_finished"
                    if failed:
                        if not policy.blocked_reason:
                            kind = "browser_failed"
                        elif policy.blocked_phase == "verification":
                            kind = "verification"
                        else:
                            kind = "approval_blocked"
                    await emit(
                        kind,
                        operation=operation,
                        verified=False if kind == "verification" else None,
                    )
                    if (metadata or {}).get("browski_verified") is True:
                        await emit("verification", operation=operation, verified=True)
            elif failed:
                if calls > 0:
                    failure_phase = "provider"
                    if provider_errors == 0:
                        provider_errors += 1
                        await emit("provider_failed")
                else:
                    failure_phase = "browser"
                    await emit("browser_failed")
        await emit("observation")

    async def before_step(agent: Agent[Any, Any]) -> None:
        if before_decision is not None:
            await before_decision()

    run: asyncio.Task[object] | None = None
    watch: asyncio.Task[bool] | None = None
    async with ManagedBrowser(
        chrome_path=config.chrome_path, headless=config.headless, highlight_elements=False
    ) as owned:
        from browser_use import Agent, ChatOpenAI

        assert owned.browser is not None
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            event_hooks={"request": [request_guard]},
            transport=_InferenceTransport(
                model_transport or httpx.AsyncHTTPTransport(retries=0, trust_env=False),
                inference_finished,
            ),
        ) as client:
            llm = ChatOpenAI(
                model=config.model,
                api_key=api_key,
                base_url="https://api.openai.com/v1",
                http_client=client,
                max_retries=0,
                timeout=30,
                temperature=None,
                frequency_penalty=None,
                max_completion_tokens=2048,
                reasoning_models=["gpt-6"],
                reasoning_effort="none",
            )
            tools = _navigation_tools(policy)
            agent: Agent[Any, Any] = Agent(
                task=goal,
                llm=llm,
                page_extraction_llm=llm,
                browser=owned.browser,
                tools=tools,
                use_vision=False,
                use_judge=False,
                flash_mode=True,
                use_thinking=False,
                max_actions_per_step=1,
                max_failures=1,
                max_history_items=6,
                file_system_path=f"{owned.workspace.name}/files",
                calculate_cost=False,
                enable_signal_handler=False,
                directly_open_url=False,
                final_response_after_failure=False,
                step_timeout=90 if approve_action is not None else 40,
                max_clickable_elements_length=8000,
            )
            try:
                await emit("task_started")
                if cancel is not None and cancel.is_set():
                    status = EngineStatus.CANCELLED
                else:
                    run = asyncio.create_task(
                        cast(Any, agent).run(
                            max_steps=config.max_steps,
                            on_step_start=before_step,
                            on_step_end=after_step,
                        )
                    )
                    if cancel is not None:
                        watch = asyncio.create_task(cancel.wait())
                    pending: set[asyncio.Task[object] | asyncio.Task[bool]] = {run}
                    if watch is not None:
                        pending.add(watch)
                    finished, _ = await asyncio.wait(
                        pending, timeout=config.timeout_seconds, return_when=asyncio.FIRST_COMPLETED
                    )
                    if cancel is not None and cancel.is_set():
                        status = EngineStatus.CANCELLED
                    elif run in finished:
                        await run
                        # The external library returns AgentHistoryList. Keep it behind
                        # this adapter, rather than storing vendor objects in task state.
                        history = cast("AgentHistoryList[Any]", cast(Any, agent).history)
                        answer = history.final_result()
                        evidence = await page_evidence(owned.browser)
                        if policy.blocked_reason:
                            status = EngineStatus.BLOCKED
                            error = policy.blocked_reason
                            failure_phase = policy.blocked_phase
                        elif criteria is not None and criteria.verify(evidence) and answer:
                            if criteria.heading.casefold() in answer.casefold():
                                status = EngineStatus.COMPLETED
                                failure_phase = None
                        if status not in {EngineStatus.COMPLETED, EngineStatus.BLOCKED}:
                            error = "Requested outcome is not independently verified."
                            if failure_phase is not None:
                                status = EngineStatus.FAILED
                            else:
                                failure_phase = "verification"
                    elif watch is not None and watch in finished:
                        status = EngineStatus.CANCELLED
                    else:
                        status = EngineStatus.BLOCKED
                        error = "Task time budget exhausted."
                        failure_phase = "timeout"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status = EngineStatus.FAILED
                failure_phase = "provider" if provider_errors else "browser"
                await emit("provider_failed" if provider_errors else "browser_failed")
                error = f"General {failure_phase} failed ({type(exc).__name__})."
            finally:
                for task in (run, watch):
                    if task is not None and not task.done():
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
    await emit("task_finished", verified=status is EngineStatus.COMPLETED)
    return EngineResult(
        status=status,
        engine="general",
        provider="openai",
        model=config.model,
        answer=answer,
        evidence=evidence,
        verified=status is EngineStatus.COMPLETED,
        steps=steps,
        action_count=actions,
        generative_calls=calls,
        provider_errors=provider_errors,
        recovery_count=recoveries,
        decision_latencies_ms=latencies,
        failure_phase=failure_phase,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        error=error,
    )
