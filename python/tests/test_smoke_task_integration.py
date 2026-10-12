"""Deterministic Luna-contract integration coverage for local smoke fixtures."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from browser_agent._types import (
    BBox,
    SemanticElement,
    SemanticSnapshot,
    TextBlock,
    Viewport,
    VisibilityClass,
)
from browser_agent.agent import AgentConfig, AgentRuntime, LunaDecisionAgent
from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)
from browser_agent.session import BrowserSession
from browser_agent.telemetry.debug_log import DebugLogConfig

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "smoke"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


async def test_harness_goal_text_uses_only_visible_viewport_elements() -> None:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from benchmarks.smoke.run_live import visible_snapshot_text

    snapshot = SemanticSnapshot(
        url="http://fixture.test",
        page_fingerprint="fixture-fingerprint",
        state_generation=1,
        viewport=Viewport(width=300, height=200),
        text_excerpt="Hidden excerpt marker",
        text_blocks=[TextBlock(kind="paragraph", text="Offscreen block marker")],
        elements=[
            SemanticElement(
                ref="@visible",
                role="status",
                text="Visible result",
                bbox=BBox(x=10, y=10, width=100, height=20),
                fingerprint="visible-fingerprint",
            ),
            SemanticElement(
                ref="@offscreen",
                role="text",
                text="Offscreen element marker",
                bbox=BBox(x=10, y=300, width=100, height=20),
                fingerprint="offscreen-fingerprint",
            ),
            SemanticElement(
                ref="@hidden",
                role="text",
                text="Hidden element marker",
                visible=False,
                visibility=VisibilityClass.HIDDEN,
                bbox=BBox(x=10, y=10, width=100, height=20),
                fingerprint="hidden-fingerprint",
            ),
            SemanticElement(
                ref="@partly-visible",
                role="text",
                text="Partly visible result",
                bbox=BBox(x=-10, y=10, width=20, height=20),
                fingerprint="partial-fingerprint",
            ),
        ],
    )

    visible_text = visible_snapshot_text(snapshot)

    assert "Visible result" in visible_text
    assert "Partly visible result" in visible_text
    assert "Offscreen element marker" not in visible_text
    assert "Hidden element marker" not in visible_text
    assert "Hidden excerpt marker" not in visible_text
    assert "Offscreen block marker" not in visible_text


class _FixtureHandler(BaseHTTPRequestHandler):
    fixture_name = "short-picker.html"

    def do_GET(self) -> None:
        body = (FIXTURES / self.fixture_name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


@contextmanager
def serve_fixture(fixture_name: str) -> Generator[str, None, None]:
    handler = type("FixtureHandler", (_FixtureHandler,), {"fixture_name": fixture_name})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _RegionProvider:
    def __init__(self) -> None:
        self.calls: list[ReasoningContext] = []

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        _ = model, effort
        self.calls.append(context)
        if context.purpose == ReasoningPurpose.PLAN:
            milestone = "The requested region is confirmed"
            return ReasoningDecision(
                outcome=ReasoningOutcome.MILESTONE_PLAN,
                milestones=[milestone],
                milestone_evidence={
                    milestone: "visible_text:Service region: Pune",
                },
            )

        region = next(
            element for element in context.observation.elements if element.name == "Service region"
        )
        confirmation = next(
            element for element in context.observation.elements if element.name == "Confirm region"
        )
        if len(self.calls) == 2:
            action = ReasoningAction(
                type="select",
                target_ref=region.ref,
                value="Pune",
                by="label",
            )
        else:
            action = ReasoningAction(type="click", target_ref=confirmation.ref)
        return ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=action,
        )


class _PreferencesProvider:
    def __init__(self) -> None:
        self.calls: list[ReasoningContext] = []
        self.actions = [
            ("type", "Full name", "Ada Lovelace"),
            ("type", "Email address", "ada@example.test"),
            ("click", "Continue to preferences", None),
            ("select", "Preferred session", "Morning lab"),
            ("check", "Send me workshop updates", True),
            ("click", "Save preferences", None),
        ]

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        _ = model, effort
        self.calls.append(context)
        if context.purpose == ReasoningPurpose.PLAN:
            elements_by_name = {item.name: item for item in context.observation.elements}
            milestones = ["Name is correct", "Email is correct", "Preferences are saved"]
            return ReasoningDecision(
                outcome=ReasoningOutcome.MILESTONE_PLAN,
                milestones=milestones,
                milestone_evidence={
                    milestones[0]: (f"field_matches_task:{elements_by_name['Full name'].ref}"),
                    milestones[1]: (f"field_matches_task:{elements_by_name['Email address'].ref}"),
                    milestones[2]: (
                        "visible_text:Registration saved for Ada Lovelace "
                        "(ada@example.test); Morning lab; updates: yes."
                    ),
                },
            )

        action_type, element_name, value = self.actions[len(self.calls) - 2]
        element = next(item for item in context.observation.elements if item.name == element_name)
        if action_type == "type":
            action = ReasoningAction(
                type="type",
                target_ref=element.ref,
                text=str(value),
            )
        elif action_type == "select":
            action = ReasoningAction(
                type="select",
                target_ref=element.ref,
                value=str(value),
                by="label",
            )
        elif action_type == "check":
            action = ReasoningAction(
                type="check",
                target_ref=element.ref,
                checked=bool(value),
            )
        else:
            action = ReasoningAction(type="click", target_ref=element.ref)
        return ReasoningDecision(outcome=ReasoningOutcome.NEXT_ACTION, action=action)


async def test_fake_luna_completes_short_dropdown_task_with_visible_evidence(
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from benchmarks.smoke.scenarios import cases

    provider = _RegionProvider()
    with serve_fixture("short-picker.html") as base_url:
        async with BrowserSession.launch(headless=True) as browser:
            await browser.navigate(f"{base_url}short")
            agent = LunaDecisionAgent(None, provider)
            async with AgentRuntime.open_sqlite(
                agent,
                browser,
                database=tmp_path / "smoke-short.sqlite",
                config=AgentConfig(max_steps=8, max_llm_calls=8),
            ) as runtime:
                result = await runtime.run(
                    'Select "Pune" in "Service region", then click '
                    '"Confirm region". Finish when visible text contains '
                    '"Service region: Pune".'
                )
            final_snapshot = await browser.observe()

    assert result.done
    assert result.status == "completed"
    assert result.steps_taken <= 8
    assert result.llm_calls <= 8
    assert any(
        "Service region: Pune" in (element.text or "") for element in final_snapshot.elements
    )
    select_fixture = await asyncio.to_thread(
        (FIXTURES / "short-picker.html").read_text,
        encoding="utf-8",
    )
    selected_region = final_snapshot.by_ref("@service_region")
    short_case = cases("http://fixture.test")[0]
    assert '<option value="pune">Pune</option>' in select_fixture
    assert selected_region is not None
    assert selected_region.value == "Pune"
    assert dict(short_case.expected_element_values)["@service_region"] == selected_region.value
    assert dict(short_case.expected_element_values)["@service_region"] != "pune"
    assert provider.calls[1].candidate_options
    assert provider.calls[2].candidate_options


async def test_fake_luna_fills_multistep_form_with_private_local_checks(
    tmp_path: Path,
) -> None:
    provider = _PreferencesProvider()
    with serve_fixture("medium-preferences.html") as base_url:
        async with BrowserSession.launch(headless=True) as browser:
            await browser.navigate(f"{base_url}registration")
            agent = LunaDecisionAgent(None, provider)
            async with AgentRuntime.open_sqlite(
                agent,
                browser,
                database=tmp_path / "smoke-medium.sqlite",
                config=AgentConfig(max_steps=16, max_llm_calls=18),
                debug_config=DebugLogConfig(enabled=True, directory=tmp_path / "debug"),
            ) as runtime:
                result = await runtime.run(
                    'Set "Full name" to "Ada Lovelace" and fill "Email address" with '
                    '"ada@example.test". Click "Continue to preferences", select '
                    '"Morning lab" in "Preferred session", and check '
                    '"Send me workshop updates". Click "Save preferences". '
                    "Finish when visible text contains "
                    '"Registration saved for Ada Lovelace (ada@example.test); '
                    'Morning lab; updates: yes."'
                )
            final_snapshot = await browser.observe()

    if not result.done:
        events_path = tmp_path / "debug" / str(result.run_id) / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        validation = [
            event["payload"]
            for event in events
            if event.get("event") == "decision.candidate_validation"
        ]
        pytest.fail(f"{result.result_summary}: {validation[-1] if validation else events[-1]}")
    assert result.status == "completed"
    assert result.steps_taken <= 16
    assert result.llm_calls <= 18
    assert any(
        "Registration saved for Ada Lovelace" in (element.text or "")
        for element in final_snapshot.elements
    )
    assert all(
        element.value is None
        for context in provider.calls
        for element in context.observation.elements
    )
    assert any(any(context.browser_checks.values()) for context in provider.calls[2:])
