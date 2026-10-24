"""Real Browser Use + headless Chrome, with every model request served offline."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from browser_agent.engines.contracts import EngineEvent, EngineStatus
from browser_agent.engines.general import GeneralConfig, run_general
from browser_agent.engines.lifecycle import ActionApproval
from browser_agent.telemetry.debug_log import DebugLogConfig, DebugRecorder

pytestmark = pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1",
    reason="opt-in real Browser Use/headless Chrome with offline inference only",
)
Action = dict[str, dict[str, Any]]


def _index(body: dict[str, Any], label: str) -> int:
    # Use exactly the live DOM supplied to the model; no fixture index guesses.
    for message in reversed(body["messages"]):
        content = message["content"]
        text = (
            content
            if isinstance(content, str)
            else "\n".join(
                str(cast(dict[str, Any], part).get("text", ""))
                for part in content
                if isinstance(part, dict)
            )
        )
        if "<browser_state>" not in text:
            continue
        match = re.search(r"\[(\d+)\]<[^\n]*" + re.escape(label), text)
        if match is None:
            match = re.search(r"\[(\d+)\]<[^\n]*\n\s*" + re.escape(label), text)
        assert match is not None, f"Missing {label!r} in browser state: {text[-6000:]}"
        return int(match[1])
    raise AssertionError("No browser state in model input")


class OfflineModel:
    def __init__(
        self, actions: list[Action | Callable[[dict[str, Any]], Action]], *, verdict: bool = True
    ) -> None:
        self.actions = actions
        self.verdict = verdict
        self.requests = 0
        self.judges = 0
        self.position = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        self.requests += 1
        body = json.loads(request.content)
        schema = body.get("response_format", {}).get("json_schema", {}).get("schema", {})
        if "verdict" in schema.get("properties", {}):
            self.judges += 1
            output = {
                "verdict": self.verdict,
                "failure_reason": ""
                if self.verdict
                else "The requested birth date was not established.",
            }
        else:
            assert self.position < len(self.actions), f"Unexpected request {self.position}"
            action = self.actions[self.position]
            self.position += 1
            if callable(action):
                action = action(body)
            output = {
                "evaluation_previous_goal": "Continue from observed state.",
                "memory": "Fixture task.",
                "next_goal": "Find the requested public information.",
                "action": [action],
            }
        return httpx.Response(
            200,
            json={
                "id": "offline-only",
                "object": "chat.completion",
                "created": 1,
                "model": "offline-fixture",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(output)},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )


def _click(label: str) -> Callable[[dict[str, Any]], Action]:
    return lambda body: {"click": {"index": _index(body, label)}}


def _input(label: str, text: str) -> Callable[[dict[str, Any]], Action]:
    return lambda body: {"input": {"index": _index(body, label), "text": text}}


def _done(text: str = "Alan Turing was born on 23 June 1912.", *, success: bool = True) -> Action:
    return {"done": {"text": text, "success": success}}


@pytest.mark.parametrize("verdict", [True, False])
async def test_seven_step_search_open_read_uses_authored_text_and_independent_judge(
    article_site: str, tmp_path: Path, verdict: bool
) -> None:
    (tmp_path / "search.html").write_text(
        '<h1>Search encyclopedia</h1><form action="results.html">'
        '<input aria-label="Search Wikipedia" name="q"><button>Search</button></form>'
    )
    (tmp_path / "results.html").write_text(
        '<h1>Results</h1><a aria-label="Alan Turing" href="article.html">Alan Turing</a>'
    )
    (tmp_path / "article.html").write_text(
        '<h1>Alan Turing</h1><a aria-label="Biography" href="biography.html">Biography</a>'
    )
    (tmp_path / "biography.html").write_text(
        "<h1>Biography</h1><p>Born 23 June 1912</p>"
        '<div style="height:1500px">Public biography</div>'
    )
    model = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/search.html", "new_tab": False}},
            _input("Search Wikipedia", "Alan Turing"),
            {"send_keys": {"keys": "Enter"}},
            _click("Alan Turing"),
            _click("Biography"),
            {"scroll": {"down": True, "pages": 0.5}},
            _done(),
        ],
        verdict=verdict,
    )
    events: list[EngineEvent] = []

    async def sink(event: EngineEvent) -> None:
        events.append(event)

    result = await run_general(
        "Search the encyclopedia for Alan Turing, open the article and biography "
        "and report his birth date.",
        GeneralConfig(allow_paid_api=True, max_steps=10, max_calls=12),
        api_key="offline-only",
        model_transport=httpx.MockTransport(model),
        event_sink=sink,
    )
    assert result.status is (
        EngineStatus.COMPLETED if verdict else EngineStatus.PARTIALLY_COMPLETED
    ), result.model_dump()
    assert result.verified is verdict
    assert result.steps == 7 and result.action_count == 6
    assert result.generative_calls == model.requests == 8 and model.judges == 1
    assert result.answer and "23 June 1912" in result.answer
    if not verdict:
        assert result.verdict_reason == "The requested birth date was not established."
    before = [e for e in events if e.kind == "action_started"]
    assert any(e.label == "Typed “Alan Turing” into Search Wikipedia" for e in before)
    assert any(e.label == "Pressed Enter" for e in before)
    assert all(e.detail == "Find the requested public information." for e in before)
    assert any(e.page_url == f"{article_site}/biography.html" for e in before)


async def test_denied_order_does_not_click_and_agent_can_choose_another_approach(
    article_site: str, tmp_path: Path
) -> None:
    (tmp_path / "order.html").write_text(
        '<h1>Review order</h1><button aria-label="Place order" '
        "onclick=\"location.href='ordered.html'\">Place order</button>"
        '<a aria-label="Help" href="help.html">Help</a>'
    )
    (tmp_path / "help.html").write_text("<h1>Help</h1>Ordering alternatives")
    model = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/order.html", "new_tab": False}},
            _click("Place order"),
            _click("Help"),
            _done("The user declined the order; opened Help.", success=False),
        ]
    )
    approvals: list[ActionApproval] = []

    async def deny(request: ActionApproval) -> bool:
        approvals.append(request)
        return False

    result = await run_general(
        "Place an order or find help if declined.",
        GeneralConfig(allow_paid_api=True),
        api_key="offline-only",
        model_transport=httpx.MockTransport(model),
        approve_action=deny,
    )
    assert len(approvals) == 1 and approvals[0].reason == "Placing an order or payment"
    assert result.evidence and result.evidence.url == f"{article_site}/help.html", (
        result.model_dump()
    )
    assert result.action_count == 2 and result.steps == 4
    assert result.status is EngineStatus.PARTIALLY_COMPLETED
    assert model.position == 4


async def test_step_exhaustion_after_navigation_is_partial(article_site: str) -> None:
    model = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/botany.html", "new_tab": False}},
            _done("I need more steps to finish.", success=False),
        ]
    )
    result = await run_general(
        "Research all articles.",
        GeneralConfig(allow_paid_api=True, max_steps=2),
        api_key="offline-only",
        model_transport=httpx.MockTransport(model),
    )
    assert result.status is EngineStatus.PARTIALLY_COMPLETED, result.model_dump()
    assert result.verdict_reason == "Task step budget exhausted."


@pytest.mark.parametrize("approve", [True, False])
async def test_password_requires_approval_and_never_enters_events_or_capture(
    article_site: str, tmp_path: Path, approve: bool
) -> None:
    (tmp_path / "password.html").write_text(
        '<h1>Account</h1><input aria-label="Password" type="password">'
    )
    secret = "offline-secret-value-927"
    model = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/password.html", "new_tab": False}},
            _input("Password", secret),
            _done("Password step finished.", success=False),
        ]
    )
    approvals: list[ActionApproval] = []
    events: list[EngineEvent] = []

    async def sink(event: EngineEvent) -> None:
        events.append(event)

    async def respond(request: ActionApproval) -> bool:
        approvals.append(request)
        return approve

    with DebugRecorder(DebugLogConfig(enabled=True, directory=tmp_path / "capture")).bind(
        "password", "session"
    ):
        result = await run_general(
            "Use the provided account form.",
            GeneralConfig(allow_paid_api=True),
            api_key="offline-only",
            model_transport=httpx.MockTransport(model),
            event_sink=sink,
            approve_action=respond,
        )
    assert len(approvals) == 1 and approvals[0].reason == "Entering a password", result.model_dump()
    assert result.action_count == (2 if approve else 1)
    assert secret not in "\n".join(e.model_dump_json() for e in events)
    assert secret not in (tmp_path / "capture/password/events.jsonl").read_text()
    if approve:
        assert any(e.label == "Typed “••••” into Password" for e in events)


async def test_cancel_inflight_inference_stops_within_two_seconds() -> None:
    entered = asyncio.Event()
    cancel = asyncio.Event()

    async def pending(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Request resumed")

    task = asyncio.create_task(
        run_general(
            "Read a page.",
            GeneralConfig(allow_paid_api=True),
            api_key="offline-only",
            cancel=cancel,
            model_transport=httpx.MockTransport(pending),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 30)
        cancel.set()
        result = await asyncio.wait_for(task, 2)
        assert result.status is EngineStatus.CANCELLED
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def test_attached_session_disconnects_and_leaves_browser_and_tabs_open(
    article_site: str,
) -> None:
    from browser_agent.engines.browser_use_runtime import ManagedBrowser
    from browser_agent.engines.contracts import CompletionCriteria

    async with ManagedBrowser(highlight_elements=False) as owner:
        assert owner.browser is not None
        await owner.browser.start()
        page = await owner.browser.get_current_page()
        assert page is not None
        await page.goto(f"{article_site}/index.html")
        original_ids = {str(target.target_id) for target in owner.browser.get_page_targets()}
        monitors_before = _storage_monitors()
        model = OfflineModel(
            [
                {"navigate": {"url": f"{article_site}/botany.html", "new_tab": False}},
                _done("Botany"),
            ]
        )
        result = await run_general(
            "Open Botany",
            GeneralConfig(allow_paid_api=True),
            api_key="offline-only",
            cdp_url=owner.browser.cdp_url,
            criteria=CompletionCriteria(url=f"{article_site}/botany.html", heading="Botany"),
            model_transport=httpx.MockTransport(model),
        )
        assert result.verified, result.model_dump()
        # Regression: a connected (not owned) session must not leak its
        # storage-state monitoring loop into the long-lived service process.
        await asyncio.sleep(0.1)
        assert _storage_monitors() == monitors_before
        assert original_ids <= {
            str(target.target_id) for target in owner.browser.get_page_targets()
        }
        assert (
            await cast(Any, page).evaluate("() => document.querySelector('h1').textContent")
            == "Botany"
        )


def _storage_monitors() -> int:
    return sum(
        1
        for task in asyncio.all_tasks()
        if task.get_name() == "monitor_storage_changes" and not task.done()
    )


@pytest.mark.parametrize("max_calls", [1, 2])
async def test_model_budget_counts_judge_and_reports_missing_verdict_as_partial(
    article_site: str, max_calls: int
) -> None:
    model = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/botany.html", "new_tab": False}},
            _done(),
        ]
    )
    result = await run_general(
        "Read Botany.",
        GeneralConfig(allow_paid_api=True, max_calls=max_calls),
        api_key="offline-only",
        model_transport=httpx.MockTransport(model),
    )
    assert result.status is EngineStatus.PARTIALLY_COMPLETED, result.model_dump()
    assert result.generative_calls == model.requests == max_calls
    assert result.verdict_reason == "Task model-call budget exhausted."
    assert model.judges == 0 and result.action_count == 1


@pytest.mark.parametrize("judge_status", [401, 500])
async def test_unavailable_judge_keeps_done_partial_with_bounded_retries(
    article_site: str, judge_status: int
) -> None:
    model = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/botany.html", "new_tab": False}},
            _done(),
        ]
    )
    attempts = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        schema = (
            json.loads(request.content)
            .get("response_format", {})
            .get("json_schema", {})
            .get("schema", {})
        )
        if "verdict" in schema.get("properties", {}):
            attempts += 1
            return httpx.Response(
                judge_status, json={"error": {"message": "Offline failure", "type": "server_error"}}
            )
        return model(request)

    result = await run_general(
        "Read Botany.",
        GeneralConfig(allow_paid_api=True),
        api_key="offline-only",
        model_transport=httpx.MockTransport(transport),
    )
    assert result.status is EngineStatus.PARTIALLY_COMPLETED, result.model_dump()
    assert result.verdict_reason == "The independent judge verdict is unavailable."
    assert attempts == (1 if judge_status == 401 else 3)
    assert result.generative_calls == 2 + attempts and result.provider_errors == attempts


@pytest.mark.parametrize("code", [401, 429, 500])
async def test_provider_errors_are_safe_specific_and_retry_at_most_twice(code: int) -> None:
    calls = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            code, json={"error": {"message": "secret-provider-body", "type": "server_error"}}
        )

    result = await run_general(
        "Read",
        GeneralConfig(allow_paid_api=True),
        api_key="offline-only",
        model_transport=httpx.MockTransport(transport),
    )
    assert result.status is EngineStatus.FAILED and result.failure_phase == "provider", (
        result.model_dump()
    )
    assert result.error == f"General provider failed: OpenAI HTTP {code}."
    assert "secret-provider-body" not in result.model_dump_json()
    assert calls == (1 if code == 401 else 3)
    assert result.generative_calls == result.provider_errors == calls


@pytest.mark.parametrize("mode", ["approve", "deny", "changed", "no_sink"])
async def test_risky_password_write_rebinds_after_approval_and_reads_actual_value(
    article_site: str, tmp_path: Path, mode: str
) -> None:
    from browser_agent.engines.browser_use_runtime import ManagedBrowser
    from browser_agent.engines.general_tools import InteractionPolicy, navigation_tools

    (tmp_path / "account.html").write_text(
        '<h1>Account</h1><input aria-label="Password" type="password">'
    )
    async with ManagedBrowser(highlight_elements=False) as owner:
        browser = owner.browser
        assert browser is not None
        await browser.start()
        page = cast(Any, await browser.get_current_page())
        await page.goto(f"{article_site}/account.html")
        state = await browser.get_browser_state_summary(include_screenshot=False, cached=False)
        index = next(
            i for i, node in state.dom_state.selector_map.items() if node.tag_name == "input"
        )
        requests: list[ActionApproval] = []

        async def approve(request: ActionApproval) -> bool:
            requests.append(request)
            if mode == "changed":
                await page.evaluate("() => document.querySelector('input').value = 'user-change'")
            return mode != "deny"

        tools = cast(
            Any,
            navigation_tools(
                InteractionPolicy(
                    goal="Use account form",
                    model_authored=True,
                    approve=None if mode == "no_sink" else approve,
                )
            ),
        )
        action = tools.registry.create_action_model().model_validate(
            {"input": {"index": index, "text": "fixture-password"}}
        )
        result = await tools.act(action, browser)
        value = await page.evaluate("() => document.querySelector('input').value")
        assert value == (
            "fixture-password" if mode == "approve" else "user-change" if mode == "changed" else ""
        )
        assert bool(result.error) is (mode != "approve"), result.model_dump()
        assert len(requests) == (0 if mode == "no_sink" else 1)
        assert "fixture-password" not in result.model_dump_json()
        if mode != "approve":
            assert not result.is_done


async def test_third_identical_click_on_an_unchanged_page_is_refused_and_task_continues(
    article_site: str, tmp_path: Path
) -> None:
    # Regression from a live run: the agent clicked a storage *heading* five
    # times instead of the 512GB option. Principle 9: detect it in code.
    (tmp_path / "configure.html").write_text(
        '<h1>Configure</h1><div role="button" aria-label="Storage heading">Storage</div>'
        '<button aria-label="512GB" onclick="document.title=\'512GB selected\';'
        "this.textContent='512GB selected'\">512GB</button>"
    )
    model = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/configure.html", "new_tab": False}},
            _click("Storage heading"),
            _click("Storage heading"),
            _click("Storage heading"),
            _click("512GB"),
            _done("512GB selected"),
        ]
    )
    events: list[EngineEvent] = []

    async def sink(event: EngineEvent) -> None:
        events.append(event)

    result = await run_general(
        "Select the 512GB storage option.",
        GeneralConfig(allow_paid_api=True, max_steps=10, max_calls=12),
        api_key="offline-only",
        model_transport=httpx.MockTransport(model),
        event_sink=sink,
    )
    refused = [e for e in events if e.kind == "approval_blocked"]
    assert len(refused) == 1, [e.model_dump() for e in events]
    assert refused[0].label == "Stopped repeating an action that had no effect"
    # navigate + two heading clicks + the option; the refused third click never ran.
    assert result.action_count == 4
    assert model.position == 6, "the agent continued after the refusal"
    assert result.verified, result.model_dump()


async def test_stale_target_is_a_recovery_and_stop_reports_only_cancellation(
    article_site: str,
) -> None:
    # Live run: a page still loading produced a red "Action refused" line and the
    # cancelled task was then summarised as an "approval failure".
    scripted = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/index.html", "new_tab": False}},
            # Nothing is focused, so there is no fresh target for the keys.
            {"send_keys": {"keys": "Enter"}},
        ]
    )
    cancel = asyncio.Event()
    waiting = asyncio.Event()

    async def model(request: httpx.Request) -> httpx.Response:
        if scripted.position < len(scripted.actions):
            return scripted(request)
        waiting.set()
        await asyncio.Event().wait()
        raise AssertionError("Request resumed")

    events: list[EngineEvent] = []

    async def sink(event: EngineEvent) -> None:
        events.append(event)

    task = asyncio.create_task(
        run_general(
            "Open the library page.",
            GeneralConfig(allow_paid_api=True),
            api_key="offline-only",
            cancel=cancel,
            model_transport=httpx.MockTransport(model),
            event_sink=sink,
        )
    )
    await asyncio.wait_for(waiting.wait(), 60)
    cancel.set()
    result = await asyncio.wait_for(task, 5)

    recoveries = [e for e in events if e.kind == "recovery"]
    assert [e.label for e in recoveries] == ["Page changed — looking again"]
    assert not [e for e in events if e.kind in {"approval_blocked", "browser_failed"}]
    assert result.status is EngineStatus.CANCELLED and result.recovery_count == 1
    assert result.failure_phase is None and result.error is None


async def test_judge_receives_evidence_criteria_against_starting_prices(
    article_site: str,
) -> None:
    # Live false success: the judge accepted a "From" base price as the price of
    # the requested configuration. The judge now gets explicit evidence criteria.
    model = OfflineModel(
        [
            {"navigate": {"url": f"{article_site}/botany.html", "new_tab": False}},
            _done("Botany"),
        ]
    )
    judge_prompts: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body.get("response_format", {}).get("json_schema", {}).get("schema", {})
        if "verdict" in schema.get("properties", {}):
            judge_prompts.append(json.dumps(body["messages"]))
        return model(request)

    result = await run_general(
        "Open the Botany page.",
        GeneralConfig(allow_paid_api=True),
        api_key="offline-only",
        model_transport=httpx.MockTransport(recording),
    )
    assert result.verified, result.model_dump()
    assert len(judge_prompts) == 1
    assert "'From', 'Starting at', base-model" in judge_prompts[0]
