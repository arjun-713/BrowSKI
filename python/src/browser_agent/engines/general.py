"""Official Browser Use Agent with bounded inference, risk approval and outcome checks."""

from __future__ import annotations

import asyncio
import tempfile
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field

from browser_agent.engines.browser_use_runtime import (
    ManagedBrowser,
    configure_browser_use,
    is_http_url,
    page_evidence,
)
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
    from browser_use.browser.session import BrowserSession


class _InferenceTransport(httpx.AsyncBaseTransport):
    """Measure every HTTP attempt, including judge, extraction and compaction."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        finished: Callable[[float, int | str], Awaitable[None]],
    ) -> None:
        self._inner = inner
        self._finished = finished

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
            await response.aread()
        except Exception as error:
            await self._finished((time.perf_counter() - started) * 1000, type(error).__name__)
            raise
        await self._finished((time.perf_counter() - started) * 1000, response.status_code)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class GeneralConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model: str = "gpt-6-luna"
    allow_paid_api: bool = False
    max_calls: int = Field(default=150, ge=1, le=500)
    max_steps: int = Field(default=60, ge=1, le=200)
    timeout_seconds: int = Field(default=1800, ge=5, le=7200)
    max_failures: int = Field(default=3, ge=1, le=10)
    step_timeout: int = Field(default=180, ge=120, le=600)
    search_engine: Literal["google", "bing", "duckduckgo"] = "google"
    reasoning_effort: Literal["none", "low", "high"] = "low"
    chrome_path: str = "/usr/bin/google-chrome"
    headless: bool = True


_STOP_SECONDS = 5

# Operating brief for the user's own browser. Approval for risky actions and
# completion checks are enforced in code; this only shapes the agent's approach.
_OPERATING_BRIEF = """
You are working in the user's own Chrome window, signed in as the user.
- When the task names sites or stores, go to each of them directly, one new tab
  per site, and use that site's own search (for example
  https://www.amazon.in/s?k=..., https://www.flipkart.com/search?q=..., or the
  brand's official store page). Do not start with a general web search for them.
  Use the regional site that matches the user's locale (for example .in).
- Keep every source tab open: the user wants to see them side by side.
- On a product or configuration page, select exactly the requested options
  (for example memory and storage separately) and confirm the selection and the
  updated price on the page before reporting it. Read option labels carefully
  before clicking; a section heading is not an option.
- A "From", "Starting at" or base-model price is not the price of a specific
  configuration. Report the price the page shows after your selections (often in
  the summary or total beside the buy button), or say it could not be confirmed.
- If an action does not change the page, do not repeat it: try a different
  element, scroll, or read the page instead.
- Do not finish early. Before reporting failure, try an alternative for every
  part of the task. If something is genuinely unavailable, say exactly what you
  found for each part (for example each store's price, variant and page).
- Answer with the concrete facts the user asked for and where you found them.
"""


@asynccontextmanager
async def _task_browser(
    config: GeneralConfig, cdp_url: str | None
) -> AsyncGenerator[tuple[BrowserSession, str]]:
    if cdp_url is None:
        async with ManagedBrowser(
            chrome_path=config.chrome_path, headless=config.headless, highlight_elements=False
        ) as owned:
            assert owned.browser is not None
            yield owned.browser, owned.workspace.name
        return
    configure_browser_use()
    from browser_use import BrowserSession

    with tempfile.TemporaryDirectory(prefix="browski-general-") as workspace:
        browser = BrowserSession(
            cdp_url=cdp_url,
            keep_alive=True,
            highlight_elements=False,
            dom_highlight_elements=False,
            enable_default_extensions=False,
            # Never change site permissions in the user's own browser.
            permissions=[],
        )
        try:
            yield browser, workspace
        finally:
            from browser_use.browser.events import BrowserStopEvent

            # With keep_alive and force=False upstream only notifies watchdogs, so
            # background loops (storage-state monitoring) end while the user's
            # browser and tabs stay open. reset then disconnects CDP without a
            # browser close or a storage export through the relay.
            with suppress(Exception):
                await asyncio.wait_for(
                    browser.event_bus.dispatch(BrowserStopEvent(force=False)),
                    timeout=_STOP_SECONDS,
                )
            await browser.reset()
            await browser.event_bus.stop(clear=True, timeout=1)


# Generic evaluation criteria for the independent judge (not a known answer).
# Upstream gives ground_truth absolute precedence over its other criteria.
_JUDGE_EVIDENCE_CRITERIA = (
    "Evaluation criteria, not a known answer: every specific value in the final "
    "answer (price, date, number, name, version) must appear in the page content "
    "the agent observed, for exactly the item, variant and configuration the task "
    "asked for. A 'From', 'Starting at', base-model or different-variant value does "
    "not satisfy a request about a specific configuration. If any reported value "
    "cannot be traced to the requested item in the trace, the verdict must be false."
)


def _completion(
    history: AgentHistoryList[Any],
    criteria: CompletionCriteria | None,
    evidence: PageEvidence | None,
    *,
    steps: int,
    max_steps: int,
    actions: int,
) -> tuple[EngineStatus, str]:
    if history.is_done() and history.is_successful() is True:
        if criteria is not None:
            if criteria.verify(evidence):
                return (
                    EngineStatus.COMPLETED,
                    "The requested page and heading were independently verified.",
                )
            return (
                EngineStatus.PARTIALLY_COMPLETED,
                "The requested page and heading were not verified.",
            )
        judgement = cast("dict[str, object] | None", cast(Any, history).judgement())
        if judgement is not None and judgement.get("verdict") is True:
            return EngineStatus.COMPLETED, "The independent judge verified completion."
        reason = (judgement or {}).get("failure_reason")
        return EngineStatus.PARTIALLY_COMPLETED, str(
            reason
            or (
                "The independent judge did not verify completion."
                if judgement
                else "The independent judge verdict is unavailable."
            )
        )[:500]
    # Upstream forces done(false) on its last step; report that as budget
    # exhaustion rather than mistaking it for an earlier site/goal block.
    if steps >= max_steps:
        return (
            EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED,
            "Task step budget exhausted.",
        )
    if history.is_done() and history.is_successful() is False:
        # The agent's own explanation is the answer; keep the verdict short.
        if actions:
            return (
                EngineStatus.PARTIALLY_COMPLETED,
                "The agent finished only part of the task; its answer explains what is missing.",
            )
        return EngineStatus.BLOCKED, "The agent could not start the task; see its answer."
    return (
        EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED,
        "The task stopped before completion could be independently verified.",
    )


async def run_general(
    goal: str,
    config: GeneralConfig,
    *,
    api_key: str | None = None,
    cdp_url: str | None = None,
    criteria: CompletionCriteria | None = None,
    event_sink: EventSink | None = None,
    cancel: asyncio.Event | None = None,
    model_transport: httpx.AsyncBaseTransport | None = None,
    before_decision: Callable[[], Awaitable[None]] | None = None,
    approve_action: ApprovalHandler | None = None,
) -> EngineResult:
    """Run one controller, with a judge when the caller supplies no outcome checks."""
    if not config.allow_paid_api:
        raise ValueError(
            "General needs a generative model; OpenAI requires explicit paid API opt-in."
        )
    if not api_key:
        from browser_agent.engines.product import EngineConfigurationError

        raise EngineConfigurationError("Add your OpenAI API key in Settings to run tasks.")
    if not goal.strip():
        raise ValueError("Task goal must not be empty.")

    started = time.perf_counter()
    calls = steps = actions = recoveries = provider_errors = 0
    evidence: PageEvidence | None = None
    answer: str | None = None
    status = EngineStatus.PARTIALLY_COMPLETED
    error: str | None = None
    verdict_reason: str | None = None
    failure_phase: str | None = None
    provider_failure: str | None = None
    budget_exhausted = False
    latencies: list[float] = []
    policy = InteractionPolicy(
        goal=goal,
        approve=approve_action,
        model_authored=True,
        search_engine=config.search_engine,
    )

    async def emit(kind: str, **values: Any) -> None:
        for key in ("page_url", "label", "detail", "error"):
            if isinstance(values.get(key), str):
                values[key] = policy.redact(values[key])
        await EngineEvent(
            kind=kind,
            engine="general",
            provider="openai",
            model=config.model,
            step=steps,
            **values,
        ).publish(event_sink)

    async def action_event(
        kind: str, operation: str, label: str, url: str | None, verified: bool | None
    ) -> None:
        nonlocal actions
        # Count executed actions (as Fast does); refused or failed ones changed nothing.
        if kind == "action_finished" and operation != "done":
            actions += 1
        await emit(
            kind,
            operation=operation,
            label=label,
            detail=policy.redact(policy.public_goal)[:500] or None,
            page_url=url if is_http_url(url) else None,
            verified=verified,
        )

    policy.notify = action_event

    async def inference_finished(latency: float, outcome: int | str) -> None:
        nonlocal provider_errors, provider_failure
        latencies.append(latency)
        failed = not isinstance(outcome, int) or outcome >= 300
        if failed:
            provider_errors += 1
            provider_failure = (
                f"OpenAI HTTP {outcome}" if isinstance(outcome, int) else f"OpenAI {outcome}"
            )
        else:
            provider_failure = None
        await emit(
            "provider_failed" if failed else "inference_finished",
            latency_ms=latency,
            label="Inference failed" if failed else "Finished thinking",
        )

    async def request_guard(request: httpx.Request) -> None:
        nonlocal calls, budget_exhausted
        if request.url.host != "api.openai.com" or request.url.scheme != "https":
            raise RuntimeError("Blocked unexpected inference destination.")
        if calls >= config.max_calls:
            budget_exhausted = True
            raise RuntimeError("Explicit hosted inference call budget exhausted.")
        calls += 1
        await emit("inference_started", label="Thinking…")

    async def after_step(agent: Agent[Any, Any]) -> None:
        nonlocal steps, evidence, failure_phase, recoveries
        steps += 1
        evidence = await page_evidence(agent.browser_session)
        if budget_exhausted or provider_failure:
            # The SDK already spent its two retry attempts. Do not multiply
            # that bound by retrying another agent decision after provider failure.
            agent.stop()
        history = cast("AgentHistoryList[Any]", cast(Any, agent).history)
        failed = history.history and any(result.error for result in history.history[-1].result)
        if failed and policy.blocked_reason and policy.blocked_phase == "freshness":
            # The page moved under the proposed target; the agent re-observes.
            # That is a bounded recovery, not a task failure.
            recoveries += 1
            await emit(
                "recovery",
                label="Page changed — looking again",
                detail=policy.redact(policy.public_goal)[:500] or None,
            )
        elif failed:
            if provider_failure:
                failure_phase, kind, label = "provider", "provider_failed", "Inference failed"
            elif policy.blocked_reason and policy.blocked_phase == "stagnation":
                failure_phase, kind = "stagnation", "approval_blocked"
                label = "Stopped repeating an action that had no effect"
            elif policy.blocked_reason:
                failure_phase, kind, label = "approval", "approval_blocked", "Action refused"
            else:
                failure_phase, kind, label = "browser", "browser_failed", "Browser operation failed"
            await emit(
                kind,
                label=label,
                verified=False,
                error=policy.blocked_reason,
                detail=policy.redact(policy.public_goal)[:500] or None,
            )
        await emit(
            "observation", page_url=evidence.url if evidence and is_http_url(evidence.url) else None
        )

    async def before_step(agent: Agent[Any, Any]) -> None:
        if before_decision is not None:
            await before_decision()

    async def model_step(state: Any, output: Any, step: int) -> None:
        # next_goal is the public action goal. Never export thinking/memory.
        policy.public_goal = output.next_goal or ""

    run: asyncio.Task[object] | None = None
    watch: asyncio.Task[bool] | None = None
    async with _task_browser(config, cdp_url) as (browser, workspace):
        from browser_use import Agent, ChatOpenAI

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
                max_retries=2,
                timeout=60,
                temperature=None,
                frequency_penalty=None,
                max_completion_tokens=4096,
                reasoning_models=["gpt-6"],
                reasoning_effort=config.reasoning_effort,
            )
            agent: Agent[Any, Any] = Agent(
                task=goal,
                llm=llm,
                page_extraction_llm=llm,
                judge_llm=llm,
                browser=browser,
                tools=_navigation_tools(policy),
                use_vision="auto",
                use_judge=criteria is None,
                ground_truth=_JUDGE_EVIDENCE_CRITERIA if criteria is None else None,
                flash_mode=False,
                use_thinking=False,
                message_compaction=True,
                # Up to three actions per decision (e.g. type, Enter, click) cuts model
                # calls. Upstream ends a batch on navigation, search, tab switches, URL
                # or focus changes and errors; every action still passes the policy
                # checks, and risky ones rebind to a fresh capture before approval.
                max_actions_per_step=3,
                max_failures=config.max_failures,
                max_history_items=30,
                file_system_path=f"{workspace}/files",
                calculate_cost=False,
                enable_signal_handler=False,
                directly_open_url=False,
                final_response_after_failure=False,
                step_timeout=config.step_timeout,
                max_clickable_elements_length=20000,
                register_new_step_callback=model_step,
                extend_system_message=_OPERATING_BRIEF,
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
                        history = cast("AgentHistoryList[Any]", cast(Any, agent).history)
                        answer = policy.redact(history.final_result() or "")[:4000] or None
                        # Agent.run closes its event bus; use the last live step
                        # observation instead of reconnecting the user's session.
                        status, verdict_reason = _completion(
                            history,
                            criteria,
                            evidence,
                            steps=steps,
                            max_steps=config.max_steps,
                            actions=actions,
                        )
                        if provider_failure and not history.is_done():
                            status = EngineStatus.FAILED
                            verdict_reason = f"General provider failed: {provider_failure}."
                            failure_phase = "provider"
                        elif budget_exhausted:
                            status = (
                                EngineStatus.PARTIALLY_COMPLETED
                                if actions
                                else EngineStatus.BLOCKED
                            )
                            verdict_reason = "Task model-call budget exhausted."
                            failure_phase = "budget"
                        elif status is EngineStatus.COMPLETED:
                            failure_phase = None
                        else:
                            failure_phase = "verification"
                        verdict_reason = policy.redact(verdict_reason)[:500]
                        if status is not EngineStatus.COMPLETED:
                            error = verdict_reason
                    else:
                        status = (
                            EngineStatus.PARTIALLY_COMPLETED if actions else EngineStatus.BLOCKED
                        )
                        verdict_reason = error = "Task time budget exhausted."
                        failure_phase = "timeout"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status = EngineStatus.FAILED
                failure_phase = "provider" if provider_failure else "browser"
                error = f"General {failure_phase} failed: {provider_failure or type(exc).__name__}."
                verdict_reason = error
                await emit("provider_failed" if provider_failure else "browser_failed")
            finally:
                for task in (run, watch):
                    if task is not None and not task.done():
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
    if status is EngineStatus.CANCELLED:
        # Stop is the outcome; an earlier, already handled refusal is not.
        failure_phase = error = verdict_reason = None
    await emit("task_finished", verified=status is EngineStatus.COMPLETED)
    return EngineResult(
        status=status,
        engine="general",
        provider="openai",
        model=config.model,
        answer=answer,
        evidence=evidence,
        verified=status is EngineStatus.COMPLETED,
        verdict_reason=verdict_reason,
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
