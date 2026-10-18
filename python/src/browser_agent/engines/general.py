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

if TYPE_CHECKING:
    from browser_use.agent.service import Agent
    from browser_use.agent.views import AgentHistoryList


class GeneralConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model: str = "gpt-6-luna"
    allow_paid_api: bool = False
    max_calls: int = Field(default=3, ge=1, le=10)
    max_steps: int = Field(default=4, ge=1, le=20)
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
) -> EngineResult:
    """Navigation/read-only slice. Product approval/extension gates are still pending."""
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
    provider_errors = 0
    answer: str | None = None
    evidence: PageEvidence | None = None
    status = EngineStatus.PARTIALLY_COMPLETED
    error: str | None = None

    async def emit(kind: str, operation: str | None = None, verified: bool | None = None) -> None:
        if event_sink is not None:
            await event_sink(
                EngineEvent(
                    kind=kind,
                    engine="general",
                    provider="openai",
                    step=steps,
                    operation=operation,
                    verified=verified,
                )
            )

    async def request_guard(request: httpx.Request) -> None:
        nonlocal calls
        if request.url.host != "api.openai.com" or request.url.scheme != "https":
            raise RuntimeError("Blocked unexpected inference destination.")
        if calls >= config.max_calls:
            raise RuntimeError("Explicit hosted inference call budget exhausted.")
        calls += 1
        await emit("inference_started")

    async def after_step(agent: Agent[Any, Any]) -> None:
        nonlocal steps, evidence, actions
        steps += 1
        evidence = await page_evidence(agent.browser_session)
        history = cast("AgentHistoryList[Any]", cast(Any, agent).history)
        if history.history:
            last = history.history[-1]
            if last.model_output:
                for action in last.model_output.action:
                    operation = next(iter(action.model_dump(exclude_none=True)), "unknown")
                    actions += int(operation != "done")
                    await emit("action_finished", operation=operation)
        await emit("observation")

    async def before_step(agent: Agent[Any, Any]) -> None:
        if before_decision is not None:
            await before_decision()

    run: asyncio.Task[object] | None = None
    watch: asyncio.Task[bool] | None = None
    async with ManagedBrowser(chrome_path=config.chrome_path, headless=config.headless) as owned:
        from browser_use import Agent, ChatOpenAI, Tools

        assert owned.browser is not None
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            event_hooks={"request": [request_guard]},
            transport=model_transport,
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
            tools: Tools[Any] = Tools()
            # The first gate needs navigation and extraction only. No form submits,
            # arbitrary page evaluation, filesystem access or consequential clicks.
            allowed = {"navigate", "go_back", "wait", "scroll", "find_text", "done"}
            for name in list(tools.registry.registry.actions):
                if name not in allowed:
                    tools.registry.exclude_action(name)
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
                step_timeout=40,
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
                    if run in finished:
                        await run
                        # The external library returns AgentHistoryList. Keep it behind
                        # this adapter, rather than storing vendor objects in task state.
                        history = cast("AgentHistoryList[Any]", cast(Any, agent).history)
                        answer = history.final_result()
                        provider_errors = sum(e is not None for e in history.errors())
                        evidence = await page_evidence(owned.browser)
                        if criteria is not None and criteria.verify(evidence) and answer:
                            if criteria.heading.casefold() in answer.casefold():
                                status = EngineStatus.COMPLETED
                        if status is not EngineStatus.COMPLETED:
                            error = "Requested outcome is not independently verified."
                    elif watch is not None and watch in finished:
                        status = EngineStatus.CANCELLED
                    else:
                        status = EngineStatus.BLOCKED
                        error = "Task time budget exhausted."
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status = EngineStatus.FAILED
                error = f"General engine failed ({type(exc).__name__})."
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
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        error=error,
    )
