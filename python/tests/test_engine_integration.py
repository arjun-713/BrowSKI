"""BROWSKI 2.0 engine lifecycle and real-browser integration boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from browser_agent.engines.contracts import CompletionCriteria


async def test_general_rejects_paid_calls_before_import_or_key_access() -> None:
    from browser_agent.engines.general import GeneralConfig, run_general

    with pytest.raises(ValueError, match="opt-in"):
        await run_general("Open an article", GeneralConfig())
    with pytest.raises(ValueError, match="Add your OpenAI API key"):
        await run_general("Open an article", GeneralConfig(allow_paid_api=True))


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1",
    reason="opt-in real Browser Use Chrome boundary; no model requests",
)
async def test_real_browser_use_navigation_has_independent_page_evidence(article_site: str) -> None:
    from browser_agent.engines.browser_use_runtime import ManagedBrowser, page_evidence

    async with ManagedBrowser() as owned:
        assert owned.browser is not None
        await owned.browser.start()
        page = await owned.browser.get_current_page()
        assert page is not None
        url = f"{article_site}/botany.html"
        await page.goto(url)
        evidence = await page_evidence(owned.browser)
        assert CompletionCriteria(url=url, heading="Botany").verify(evidence)


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1",
    reason="opt-in real Browser Use Agent with offline model responses",
)
@pytest.mark.parametrize("false_done", [False, True])
async def test_official_agent_executes_and_checks_real_browser_without_paid_inference(
    article_site: str,
    false_done: bool,
) -> None:
    from browser_agent.engines.general import GeneralConfig, run_general

    url = f"{article_site}/botany.html"
    calls: list[str] = []

    def offline_model(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        calls.append(str(request.url))
        action = (
            {"navigate": {"url": url, "new_tab": False}}
            if len(calls) == 1 and not false_done
            else {"done": {"text": "The heading is Botany.", "success": True}}
        )
        return httpx.Response(
            200,
            json={
                "id": "offline-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "offline-fixture",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"action": [action]}),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    result = await run_general(
        f"Open {url} and report the heading.",
        GeneralConfig(allow_paid_api=True, max_calls=2),
        api_key="offline-fixture-only",
        criteria=CompletionCriteria(url=url, heading="Botany"),
        model_transport=httpx.MockTransport(offline_model),
    )
    assert result.verified is (not false_done), result.model_dump()
    assert result.generative_calls == (1 if false_done else 2)
    assert len(calls) == result.generative_calls
    if not false_done:
        assert result.evidence is not None and result.evidence.headings == ["Botany"]


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1",
    reason="real Browser Use cancellation while an offline inference request is pending",
)
async def test_cancellation_interrupts_an_inflight_model_request_without_paid_calls() -> None:
    import asyncio

    from browser_agent.engines.contracts import EngineStatus
    from browser_agent.engines.general import GeneralConfig, run_general

    entered = asyncio.Event()
    cancel = asyncio.Event()

    async def waiting_model(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Cancelled request unexpectedly resumed.")

    task = asyncio.create_task(
        run_general(
            "Read a page heading.",
            GeneralConfig(allow_paid_api=True),
            api_key="offline-fixture-only",
            cancel=cancel,
            model_transport=httpx.MockTransport(waiting_model),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=30)
        cancel.set()
        result = await asyncio.wait_for(task, timeout=30)
        assert result.status is EngineStatus.CANCELLED
        assert not result.verified
        assert result.generative_calls == 1
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.skipif(
    os.environ.get("BROWSKI_LAYA_E2E") != "1",
    reason="opt-in live CPU Laya task; requires prepared pinned checkpoint and engines extras",
)
@pytest.mark.parametrize(
    "goal,path,heading,min_actions",
    [
        ("Open the Botany article.", "botany.html", "Botany", 1),
        ("Open Botany, then open its Leaf structure article.", "leaf.html", "Leaf structure", 2),
    ],
)
async def test_live_laya_finishes_real_navigation_tasks(
    article_site: str, goal: str, path: str, heading: str, min_actions: int
) -> None:
    from browser_agent.engines.fast import run_fast
    from browser_agent.engines.fast_providers import LayaFastProvider

    root = Path(__file__).parents[2]
    provider = LayaFastProvider(root / ".browser-data/laya-browser-v19s")
    result = await run_fast(
        goal,
        f"{article_site}/index.html",
        provider,
        criteria=CompletionCriteria(url=f"{article_site}/{path}", heading=heading),
    )
    print(
        json.dumps(
            {
                "result": result.model_dump(mode="json"),
                "model_load_ms": provider.load_ms,
                "peak_rss_mib": provider.peak_rss_mib,
            }
        )
    )
    assert result.verified, result.model_dump()
    assert result.action_count >= min_actions
    assert result.generative_calls == 0


async def test_product_defaults_and_explicit_hosted_denial_are_independent_of_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from browser_agent.cli.config import ExecutionEngine, TextProviderName, load_config
    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.lifecycle import TaskControl
    from browser_agent.engines.product import EngineConfigurationError, execute_managed_task

    config = load_config()
    from browser_agent.cli.config import AgentConfig

    defaults = AgentConfig(orchestrator="langgraph")
    assert defaults.engine is ExecutionEngine.GENERAL
    assert defaults.text_provider is TextProviderName.OPENAI
    assert defaults.allow_paid_api
    monkeypatch.setenv("OPENAI_API_KEY", "offline-permission-test")
    hosted = replace(
        config,
        agent=replace(
            config.agent,
            engine=ExecutionEngine.GENERAL,
            text_provider=TextProviderName.OPENAI,
            allow_paid_api=False,
        ),
    )

    async def events(event: EngineEvent) -> None:
        raise AssertionError("Permission denial must happen before engine execution")

    with pytest.raises(EngineConfigurationError, match="permit paid"):
        await execute_managed_task(
            "Read",
            hosted,
            start_url=None,
            criteria=None,
            events=events,
            control=TaskControl("general", "openai", events),
        )


async def test_pause_boundary_resumes_and_stop_unblocks_pause() -> None:
    import asyncio

    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.lifecycle import TaskControl

    seen: list[str] = []
    paused = asyncio.Event()

    async def events(event: EngineEvent) -> None:
        seen.append(event.kind)
        paused.set()

    control = TaskControl("fast", "laya", events)
    control.pause()
    boundary = asyncio.create_task(control.decision_boundary())
    await asyncio.wait_for(paused.wait(), 1)
    assert not boundary.done()
    control.resume()
    await asyncio.wait_for(boundary, 1)
    assert seen == ["task_paused", "task_resumed"]
    control.pause()
    control.stop()
    await asyncio.wait_for(control.decision_boundary(), 1)
    assert control.cancel.is_set()


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome/offline provider failure"
)
async def test_general_http_failure_is_a_provider_error_not_a_browser_error() -> None:
    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.general import GeneralConfig, run_general

    events: list[EngineEvent] = []

    async def sink(event: EngineEvent) -> None:
        events.append(event)

    result = await run_general(
        "Read a page heading.",
        GeneralConfig(allow_paid_api=True, max_calls=1),
        api_key="offline-fixture-only",
        event_sink=sink,
        model_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                500,
                json={"error": {"message": "Offline provider unavailable", "type": "server_error"}},
            )
        ),
    )
    assert not result.verified and result.action_count == 0
    assert result.provider_errors == 1
    assert result.failure_phase == "provider"
    assert any(event.kind == "provider_failed" for event in events)
    assert not any(event.kind == "browser_failed" for event in events)
    assert len(result.decision_latencies_ms) == 1


async def test_managed_opt_in_debug_records_events_and_safe_counters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from browser_agent.cli.config import load_config
    from browser_agent.engines import product
    from browser_agent.engines.contracts import EngineEvent, EngineResult, EngineStatus
    from browser_agent.engines.lifecycle import TaskControl
    from browser_agent.telemetry.debug_log import DebugLogConfig

    config = replace(
        load_config(), debug=DebugLogConfig(enabled=True, directory=tmp_path / "capture")
    )

    async def selected(*args: object, **kwargs: object) -> EngineResult:
        await EngineEvent(kind="provider_failed", provider="laya", model="fixture").publish(None)
        return EngineResult(
            status=EngineStatus.FAILED,
            provider="laya",
            model="fixture",
            provider_errors=1,
            failure_phase="provider",
        )

    async def events(event: EngineEvent) -> None:
        pass

    monkeypatch.setattr(product, "_execute_selected_task", selected)
    result = await product.execute_managed_task(
        "Read public article",
        config,
        start_url=None,
        criteria=None,
        events=events,
        control=TaskControl("fast", "laya", events),
        run_id="debug-fixture",
        session_id="session-fixture",
    )
    capture = tmp_path / "capture/debug-fixture/events.jsonl"
    records = [json.loads(line) for line in capture.read_text().splitlines()]
    assert [record["event"] for record in records] == [
        "task.received",
        "engine.event",
        "task.result",
    ]
    assert result.run_id == "debug-fixture"
    assert records[-1]["payload"]["provider_errors"] == 1
    assert records[-1]["payload"]["failure_phase"] == "provider"
    assert "answer" not in records[-1]["payload"] and "evidence" not in records[-1]["payload"]
    assert capture.stat().st_mode & 0o777 == 0o600


def test_engine_failure_timeline_and_result_preserve_category_and_counts() -> None:
    from browser_agent.engines.contracts import EngineEvent, EngineResult, EngineStatus
    from browser_agent.extension.engine_tasks import result_summary, timeline_payload

    for kind, label, status in [
        ("provider_failed", "Inference failed", "failed"),
        ("browser_failed", "Browser operation failed", "failed"),
        ("tab_selected", "Selected browser tab", "info"),
    ]:
        event = timeline_payload(
            EngineEvent(kind=kind, provider="laya", model="fixture", step=2),
            session_id="s",
            run_id="r",
            sequence=3,
            request_id=None,
        )
        assert event is not None and event["status"] == status and event["label"] == label
    result = EngineResult(
        status=EngineStatus.FAILED,
        provider="laya",
        model="fixture",
        provider_errors=1,
        failure_phase="provider",
        steps=2,
        generative_calls=0,
    )
    summary = result_summary(result)
    assert "1 provider errors" in summary and "0 generative calls" in summary
    assert "outcome unverified" in summary and "provider failure" in summary


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome/sanitized decision replay"
)
async def test_detailed_fast_capture_round_trips_a_bounded_public_navigation_input(
    article_site: str,
    tmp_path: Path,
) -> None:
    from browser_agent.engines.fast import FastConfig, run_fast
    from browser_agent.engines.fast_contract import FastDecision, FastRequest, normalize_response
    from browser_agent.telemetry.debug_log import DebugLogConfig, DebugRecorder

    class FixtureProvider:
        name = "fixture"
        model = "deterministic-navigation-fixture"

        async def predict(self, request: FastRequest) -> FastDecision:
            target = next(c.id for c in request.observation.candidates if c.label == "Botany")
            answers: dict[str, dict[str, object]] = {}
            for name, question in request.questions.items():
                selected = "CLICK" if name == "operation" else target
                answers[name] = {
                    "choice": selected,
                    "probabilities": {key: float(key == selected) for key in question.criteria},
                }
            return normalize_response(
                request, {"answers": answers}, provider=self.name, model=self.model, latency_ms=0
            )

        async def aclose(self) -> None:
            pass

    directory = tmp_path / "capture"
    with DebugRecorder(DebugLogConfig(enabled=True, directory=directory)).bind(
        "fixture", "session"
    ):
        result = await run_fast(
            "Open Botany",
            f"{article_site}/index.html",
            FixtureProvider(),
            FastConfig(detailed_trace=True),
            criteria=CompletionCriteria(url=f"{article_site}/botany.html", heading="Botany"),
        )
    assert result.verified
    records = [
        json.loads(line) for line in (directory / "fixture/events.jsonl").read_text().splitlines()
    ]
    saved = next(
        record["payload"] for record in records if record["event"] == "fast.decision_input"
    )
    request = FastRequest.model_validate(saved)
    assert request.version == "browski.fast.v2"
    assert all(candidate.value == "[REDACTED]" for candidate in request.observation.candidates)
    assert any(record["event"] == "fast.decision_result" for record in records)


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome mutable-link grounding"
)
async def test_href_change_invalidates_a_decision_before_click_without_changing_text(
    article_site: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from browser_agent.engines import fast
    from browser_agent.engines.fast_browser import FastBrowser
    from browser_agent.engines.fast_contract import (
        FastDecision,
        FastObservation,
        FastRequest,
        Operation,
    )

    browser = FastBrowser()
    original_observe = browser.observe_links
    initialized = False

    async def stable_first_observation(hosts: set[str]) -> FastObservation:
        nonlocal initialized
        current = await original_observe(hosts)
        if not initialized:
            for _ in range(4):
                refreshed = await original_observe(hosts)
                if refreshed.id == current.id:
                    initialized = True
                    return refreshed
                current = refreshed
            raise AssertionError("Fixture must stabilize before the href-only mutation")
        return current

    monkeypatch.setattr(browser, "observe_links", stable_first_observation)

    def owned(*, chrome_path: str, headless: bool) -> FastBrowser:
        return browser

    monkeypatch.setattr(fast, "FastBrowser", owned)

    class MutatingFixture:
        name = "fixture"
        model = "mutating-link-regression"
        calls = 0

        async def predict(self, request: FastRequest) -> FastDecision:
            self.calls += 1
            if self.calls == 1:
                target = next(c.id for c in request.observation.candidates if c.label == "Botany")
                assert browser.browser is not None
                page = await browser.browser.get_current_page()
                assert page is not None
                await cast(Any, page).evaluate(
                    "() => {document.querySelector('a[href=\"botany.html\"]')"
                    ".href='astronomy.html'}"
                )
                return FastDecision(
                    observation_id=request.observation.id,
                    provider=self.name,
                    model=self.model,
                    operation=Operation.CLICK,
                    candidate_id=target,
                    latency_ms=0,
                )
            return FastDecision(
                observation_id=request.observation.id,
                provider=self.name,
                model=self.model,
                operation=Operation.BLOCKED,
                latency_ms=0,
            )

        async def aclose(self) -> None:
            pass

    result = await fast.run_fast(
        "Open Botany",
        f"{article_site}/index.html",
        MutatingFixture(),
        criteria=CompletionCriteria(url=f"{article_site}/botany.html", heading="Botany"),
    )
    assert result.action_count == 0, result.model_dump()
    assert result.recovery_count == 1
    assert not result.verified


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="optional Browser Use tool-policy boundary"
)
@pytest.mark.parametrize(
    "url",
    [
        "file://localhost/tmp/example.html",
        "javascript:alert(1)",
        "data:text/html,test",
        "https://user:pass@example.org/",
    ],
)
async def test_general_rejects_non_web_or_credential_navigation_before_upstream_execution(
    url: str,
) -> None:
    from browser_agent.engines.browser_use_runtime import configure_browser_use
    from browser_agent.engines.general import (
        _navigation_tools,  # pyright: ignore[reportPrivateUsage]
    )

    configure_browser_use()

    class Proposal:
        def model_dump(self, **kwargs: object) -> dict[str, object]:
            return {"navigate": {"url": url, "new_tab": False}}

    tools = _navigation_tools()
    result = await cast(Any, tools).act(Proposal(), None)
    assert result.error == "Only HTTP(S) navigation without credentials is permitted."


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome destination metadata"
)
async def test_link_observation_ignores_malformed_urls_and_removes_destination_queries(
    article_site: str,
    tmp_path: Path,
) -> None:
    from browser_agent.engines.fast_browser import FastBrowser

    with (tmp_path / "index.html").open("a") as fixture:
        fixture.write(
            '<a href="https://[broken">Broken destination</a>'
            '<a href="http://user:pass@127.0.0.1/">Credential destination</a>'
            '<a href="botany.html?filter=plants#overview">Botany overview</a>'
        )
    async with FastBrowser() as owned:
        assert owned.browser is not None
        await owned.browser.start()
        page = await owned.browser.get_current_page()
        assert page is not None
        await page.goto(f"{article_site}/index.html")
        observation = await owned.observe_links({"127.0.0.1"})
        labels = {candidate.label for candidate in observation.candidates}
        assert "Broken destination" not in labels and "Credential destination" not in labels
        overview = next(
            candidate
            for candidate in observation.candidates
            if candidate.label == "Botany overview"
        )
        assert overview.href == f"{article_site}/botany.html"


@pytest.mark.parametrize("decision", ["approve", "deny", "stop", "timeout"])
async def test_managed_approval_is_one_use_and_stop_timeout_fail_closed(decision: str) -> None:
    import asyncio

    from browser_agent.engines.lifecycle import ActionApproval, TaskControl

    requests: list[ActionApproval | None] = []
    entered = asyncio.Event()

    async def events(event: object) -> None:
        pass

    async def approvals(request: ActionApproval | None) -> None:
        requests.append(request)
        if request is not None:
            entered.set()

    control = TaskControl("general", "fixture", events, approvals=approvals)
    request = ActionApproval(action="click", target="Confirm local demo")
    pending = asyncio.create_task(control.request_approval(request, wait_seconds=0.1))
    await asyncio.wait_for(entered.wait(), 1)
    assert not control.respond_to_approval("a-different-action", True)
    if decision == "stop":
        control.stop()
    elif decision != "timeout":
        assert control.respond_to_approval(request.approval_id, decision == "approve")
        assert not control.respond_to_approval(request.approval_id, True)
    assert await asyncio.wait_for(pending, 1) is (decision == "approve")
    assert requests == [request, None]
    assert not control.respond_to_approval(request.approval_id, True)


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome approval policy"
)
@pytest.mark.parametrize(
    "mode", ["approve", "deny", "changed", "append", "inferred", "password", "controls"]
)
async def test_fast_literal_tools_keep_exact_literal_approval_and_unchanged_page(
    article_site: str, tmp_path: Path, mode: str
) -> None:
    from browser_agent.engines.browser_use_runtime import ManagedBrowser
    from browser_agent.engines.general_tools import InteractionPolicy, navigation_tools
    from browser_agent.engines.lifecycle import ActionApproval

    (tmp_path / "input.html").write_text(
        '<h1>Local text entry</h1><label>Name<input id="name" name="name"></label>'
    )
    async with ManagedBrowser(highlight_elements=False) as owned:
        browser = owned.browser
        assert browser is not None
        await browser.start()
        page = cast(Any, await browser.get_current_page())
        assert page is not None
        await page.goto(f"{article_site}/input.html")
        if mode == "password":
            await page.evaluate("() => document.querySelector('input').type = 'password'")
        state = await browser.get_browser_state_summary(include_screenshot=False, cached=False)
        index = next(i for i, n in state.dom_state.selector_map.items() if n.tag_name == "input")
        approvals: list[str] = []

        async def approve(request: ActionApproval) -> bool:
            approvals.append(request.approval_id)
            assert request.target == "Name"
            if mode == "changed":
                # A live property change has no HTML-attribute mutation.
                await page.evaluate("() => document.querySelector('input').value = 'Someone else'")
            return mode != "deny"

        goal = 'Type "Ad\ta" into Name.' if mode == "controls" else 'Type "Ada" into Name.'
        policy = InteractionPolicy(goal=goal, approve=approve)
        tools = cast(Any, navigation_tools(policy))
        action_type = tools.registry.create_action_model()
        action = action_type.model_validate(
            {
                "input": {
                    "index": index,
                    "text": "Grace"
                    if mode == "inferred"
                    else "Ad\ta"
                    if mode == "controls"
                    else "Ada",
                    "clear": mode != "append",
                }
            }
        )
        result = await tools.act(action, browser)
        actual = await page.evaluate("() => document.querySelector('input').value")
        assert actual == (
            "Ada" if mode == "approve" else "Someone else" if mode == "changed" else ""
        ), result.model_dump()
        assert bool(result.error) is (mode != "approve")
        assert len(approvals) == (
            0 if mode in {"append", "inferred", "password", "controls"} else 1
        )
        if mode == "approve":
            assert result.metadata is not None and result.metadata["browski_verified"] is True


async def test_approval_clears_before_a_prior_pause_and_resume_is_still_required() -> None:
    import asyncio

    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.lifecycle import ActionApproval, TaskControl

    visible = asyncio.Event()
    cleared = asyncio.Event()
    paused = asyncio.Event()

    async def events(event: EngineEvent) -> None:
        if event.kind == "task_paused":
            paused.set()

    async def approvals(request: ActionApproval | None) -> None:
        (visible if request else cleared).set()

    control = TaskControl("general", "fixture", events, approvals=approvals)
    control.pause()
    request = ActionApproval(action="input", target="name")
    pending = asyncio.create_task(control.request_approval(request))
    await asyncio.wait_for(visible.wait(), 1)
    assert control.respond_to_approval(request.approval_id, True)
    await asyncio.wait_for(cleared.wait(), 1)
    await asyncio.wait_for(paused.wait(), 1)
    assert not pending.done()
    assert not control.respond_to_approval(request.approval_id, True)
    control.resume()
    assert await asyncio.wait_for(pending, 1)


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome bounded candidate selection"
)
async def test_fast_large_page_uses_deterministic_bounded_candidates_instead_of_failing(
    article_site: str, tmp_path: Path
) -> None:
    from browser_agent.engines.fast_browser import FastBrowser

    links = "".join(
        f'<a href="botany.html?item={index}" style="display:inline-block;width:80px">'
        f"Item {index:03}</a>"
        for index in range(160)
    )
    (tmp_path / "large.html").write_text("<h1>Large index</h1>" + links)
    async with FastBrowser() as owner:
        assert owner.browser is not None
        await owner.browser.start()
        page = await owner.browser.get_current_page()
        assert page is not None
        await page.goto(f"{article_site}/large.html")
        first = await owner.observe_links({"127.0.0.1"})
        second = await owner.observe_links({"127.0.0.1"})
        assert len(first.candidates) == len(second.candidates) == 120
        assert first.candidates == second.candidates
        assert first.text.startswith("[Candidates truncated: showing 120 of 160;")
        assert [c.label for c in first.candidates] == [f"Item {i:03}" for i in range(120)]
