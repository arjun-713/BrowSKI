"""Same-fixture task checks across managed, attached, and panel execution."""

from __future__ import annotations

import asyncio
import os
import traceback
from dataclasses import dataclass
from importlib import import_module
from typing import cast
from urllib.parse import urlsplit

import pytest

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
from extension.test_browser_e2e import AttachedHarness, use_scripted_reasoner

pytest_plugins = ("extension.test_browser_e2e",)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("BROWSKI_EXTENSION_E2E") != "1",
        reason="set BROWSKI_EXTENSION_E2E=1 to launch a real extension browser",
    ),
]


@dataclass(frozen=True)
class DifferentialCase:
    name: str
    path: str
    instruction: str
    actions: tuple[tuple[str, str, str | None], ...]
    evidence: str
    gold_fields: tuple[tuple[str, str], ...] = ()
    gold_text: str | None = None
    gold_tab_path: str | None = None


class ScenarioReasoner:
    """Return a fixed, bounded decision script for one local fixture task."""

    def __init__(self, case: DifferentialCase, guide_url: str) -> None:
        self.case = case
        self.guide_url = guide_url
        self.calls = 0
        self.last_error: str | None = None
        self.context_trace: list[dict[str, object]] = []

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        self.calls += 1
        self.context_trace.append(
            {
                "purpose": context.purpose.value,
                "steps_taken": context.task.steps_taken,
                "names": [item.name for item in context.observation.elements if item.name],
                "candidates": list(context.candidate_options.values()),
            }
        )
        try:
            return await self._reason(context, model=model, effort=effort)
        except Exception as error:
            self.last_error = f"{type(error).__name__}: {error}"
            raise

    async def _reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        del model, effort
        if context.purpose == ReasoningPurpose.PLAN:
            milestone = f"Complete differential case {self.case.name}"
            if self.case.name == "name_fill":
                target = _element(context, "Full name")
                evidence = f"field_matches_task:{target.ref}"
            else:
                evidence = f"visible_text:{self.case.evidence}"
            return ReasoningDecision(
                outcome=ReasoningOutcome.MILESTONE_PLAN,
                milestones=[milestone],
                milestone_evidence={milestone: evidence},
                current_subgoal=milestone,
            )

        action_index = context.task.steps_taken
        if action_index >= len(self.case.actions):
            milestone = f"Complete differential case {self.case.name}"
            return ReasoningDecision(
                outcome=ReasoningOutcome.TASK_COMPLETE,
                milestones=[milestone],
                milestone_evidence={milestone: self._evidence(context)},
                summary="The deterministic fixture task reached its gold condition.",
            )

        action_type, target_name, action_value = self.case.actions[action_index]
        if action_type == "activate_owned_tab":
            candidate = next(
                (
                    candidate_id
                    for candidate_id, description in context.candidate_options.items()
                    if description.startswith("Activate the already owned tab labeled ")
                    or description == "Activate another already owned browser tab."
                ),
                None,
            )
            if candidate is None:
                raise AssertionError(
                    "owned supporting tab candidate is missing; options="
                    f"{list(context.candidate_options.values())}"
                )
            return ReasoningDecision(
                outcome=ReasoningOutcome.NEXT_ACTION,
                candidate_id=candidate,
                summary="Activate the explicitly requested supporting tab.",
            )
        target = _element(context, target_name)
        if action_type == "type":
            action = ReasoningAction(type="type", target_ref=target.ref, text=action_value)
        elif action_type == "click":
            action = ReasoningAction(type="click", target_ref=target.ref)
        else:
            raise AssertionError(f"unsupported fixture action {action_type!r}")
        return ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=action,
            summary=f"Follow fixed step {action_index + 1} of the local fixture task.",
        )

    def _evidence(self, context: ReasoningContext) -> str:
        if self.case.name == "name_fill":
            target = _element(context, "Full name")
            return f"field_matches_task:{target.ref}"
        return f"visible_text:{self.case.evidence}"


def _element(context: ReasoningContext, accessible_name: str):
    element = next(
        (item for item in context.observation.elements if item.name == accessible_name),
        None,
    )
    if element is None:
        available = [item.name for item in context.observation.elements if item.name]
        raise AssertionError(
            f"expected accessible name {accessible_name!r} is missing; available={available}"
        )
    return element


def _cases(guide_url: str) -> tuple[DifferentialCase, ...]:
    return (
        DifferentialCase(
            name="name_fill",
            path="",
            instruction='Type "Differential Applicant" into "Full name" and stop.',
            actions=(("type", "Full name", "Differential Applicant"),),
            evidence="Application ready for review",
            gold_fields=(("Full name", "Differential Applicant"),),
        ),
        # The earlier fixture's email field was rejected by the privacy
        # policy without explicit user approval. This replacement is a new
        # non-PII fixture case, not a pass result for that original case.
        DifferentialCase(
            name="multi_field_form",
            path="extension-multifield.html",
            instruction=(
                'Fill "Project code" with "DIFF-42"; '
                'fill "Preferred city" with "Pune"; '
                'fill "Supporting reference code" with "LOCAL-42"; '
                'stop when "Local form ready for review." appears.'
            ),
            actions=(
                ("type", "Project code", "DIFF-42"),
                ("type", "Preferred city", "Pune"),
                ("type", "Supporting reference code", "LOCAL-42"),
            ),
            evidence="Local form ready for review.",
            gold_fields=(
                ("Project code", "DIFF-42"),
                ("Preferred city", "Pune"),
                ("Supporting reference code", "LOCAL-42"),
            ),
            gold_text="Local form ready for review.",
        ),
        DifferentialCase(
            name="spa_rerender",
            path="extension-reliability.html?scenario=spa",
            instruction=(
                'Click "Start dynamic stage"; wait for the rerender; '
                'click "Continue after SPA rerender"; stop when "Dynamic task completed.".'
            ),
            actions=(
                ("click", "Start dynamic stage", None),
                ("click", "Continue after SPA rerender", None),
            ),
            evidence="Dynamic task completed.",
            gold_text="Dynamic task completed.",
        ),
        DifferentialCase(
            name="multi_tab",
            path="extension-multitab.html",
            instruction=(
                'Click "Open internship reference guide" in a new tab; read the '
                'heading "Internship reference guide"; then stop.'
            ),
            actions=(
                ("click", "Open internship reference guide", None),
                ("activate_owned_tab", "", None),
            ),
            evidence="Internship reference guide",
            gold_text="Internship reference guide",
            gold_tab_path="/guide.html",
        ),
        DifferentialCase(
            name="overlay_recovery",
            path="extension-reliability.html?scenario=recovery",
            instruction=(
                'Click "Show recoverable overlay"; dismiss "Temporary blocking overlay"; '
                'click "Complete task after recovery"; stop when "Recovery task completed.".'
            ),
            actions=(
                ("click", "Show recoverable overlay", None),
                ("click", "Dismiss blocking overlay", None),
                ("click", "Complete task after recovery", None),
            ),
            evidence="Recovery task completed.",
            gold_text="Recovery task completed.",
        ),
        DifferentialCase(
            name="ten_action_journey",
            path="extension-reliability.html?scenario=journey",
            instruction=(
                "Advance through all ten journey stages, rechecking the page after each "
                'rerender, and stop when "Journey complete after ten verified actions.".'
            ),
            actions=tuple(
                ("click", f"Advance to journey stage {stage}", None) for stage in range(1, 11)
            ),
            evidence="Journey complete after ten verified actions.",
            gold_text="Journey complete after ten verified actions.",
        ),
    )


def _case_id(index: int) -> str:
    return _cases("http://x/guide.html")[index].name


def _timeline_events(service: object) -> list[dict[str, object]]:
    """Read captured E2E events without exposing service internals to runtime code."""
    return cast(list[dict[str, object]], getattr(service, "_timeline_events", []))


async def _run_graph(
    browser: BrowserSession,
    case: DifferentialCase,
    guide_url: str,
    base_url: str,
) -> tuple[str, int, str | None]:
    await browser.navigate(f"{base_url}{case.path}")
    if case.path.startswith("extension-reliability.html"):
        await _wait_for_fixture_ready(browser)
    reasoner = ScenarioReasoner(case, guide_url)
    agent = LunaDecisionAgent(None, reasoner)
    runtime = AgentRuntime(
        agent,
        browser,
        AgentConfig(
            max_steps=20,
            max_llm_calls=24,
            max_stagnant_steps=5,
            max_recovery_actions=3,
            max_replans=1,
        ),
    )
    result = await asyncio.wait_for(
        runtime.run(case.instruction, run_id=f"diff-{case.name}"),
        timeout=75,
    )
    failure = reasoner.last_error
    if failure is not None:
        failure = f"{failure}; contexts={reasoner.context_trace}"
    if result.status == "awaiting_user":
        try:
            pending = await runtime.pending_confirmation_details(f"diff-{case.name}")
        except ValueError:
            pending = None
        failure = f"{failure}; pending_confirmation={pending}"
    if result.status != "completed":
        failure = f"{failure}; contexts={reasoner.context_trace}; result={result!r}"
    return result.status, result.steps_taken, failure


async def _wait_for_fixture_ready(browser: BrowserSession) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await browser.observe()
        if any(element.text == "Reliability fixture ready." for element in snapshot.elements):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("reliability fixture did not finish initialization")


async def _gold_from_snapshot(
    browser: BrowserSession,
    case: DifferentialCase,
    *,
    base_url: str,
) -> bool:
    snapshot = await browser.observe()
    for label, value in case.gold_fields:
        item = next(
            (element for element in snapshot.elements if element.accessible_name == label),
            None,
        )
        if item is None or item.value != value:
            return False
    if case.gold_text and case.gold_text not in "\n".join(
        element.text or "" for element in snapshot.elements
    ):
        return False
    if case.gold_tab_path:
        tabs = await browser.tabs()
        if not any(urlsplit(tab.url).path == case.gold_tab_path for tab in tabs):
            return False
    del base_url
    return True


async def _gold_diagnostic(browser: BrowserSession, case: DifferentialCase) -> str:
    snapshot = await browser.observe()
    elements = [
        {
            "name": element.accessible_name,
            "text": element.text,
            "value": element.value,
        }
        for element in snapshot.elements
    ]
    tabs = [tab.url for tab in await browser.tabs()]
    return (
        f"elements={elements}; tabs={tabs}; "
        f"expected_fields={case.gold_fields}; expected_text={case.gold_text!r}"
    )


async def _reset_page(harness: AttachedHarness, case: DifferentialCase) -> None:
    await harness.demo.goto(f"{_base_url(harness.demo.url)}{case.path}")


def _base_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


@pytest.mark.parametrize("case_index", range(6), ids=_case_id)
async def test_same_fixture_gold_across_managed_attached_and_extension_modes(
    case_index: int,
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = attached_harness
    base_url = _base_url(harness.demo.url)
    guide_url = f"{base_url}guide.html"
    case = _cases(guide_url)[case_index]
    await _reset_page(harness, case)

    # Mode A: managed Chromium, same local URL, instructions, provider decisions,
    # completion gold and per-case timeout as the attached modes.
    async with BrowserSession.launch(headless=True) as managed:
        status_a, steps_a, failure_a = await _run_graph(
            managed,
            case,
            guide_url,
            base_url,
        )
        gold_a = await _gold_from_snapshot(managed, case, base_url=base_url)
        assert status_a == "completed", (case.name, status_a, steps_a, failure_a)
        assert gold_a, (
            f"Mode A failed independent fixture gold: {case.name}; "
            f"{await _gold_diagnostic(managed, case)}"
        )

    # Mode B: use the attached Rust browser backend and Python graph directly.
    await _reset_page(harness, case)
    status_b, steps_b, failure_b = await _run_graph(
        harness.browser,
        case,
        guide_url,
        base_url,
    )
    gold_b = await _gold_from_snapshot(harness.browser, case, base_url=base_url)
    assert status_b == "completed", (case.name, status_b, steps_b, failure_b)
    assert gold_b, (
        f"Mode B failed independent fixture gold: {case.name}; "
        f"{await _gold_diagnostic(harness.browser, case)}"
    )

    # Mode C: the same attached browser, submitted through the real extension.
    await _reset_page(harness, case)
    reasoner = ScenarioReasoner(case, guide_url)
    use_scripted_reasoner(monkeypatch, reasoner)
    failure_trace: list[str] = []
    service_module = import_module("browser_agent.extension.service")

    def capture_task_failure(message: str, *args: object, **kwargs: object) -> None:
        del message, args, kwargs
        failure_trace.append(traceback.format_exc())

    monkeypatch.setattr(service_module.logger, "error", capture_task_failure)
    await harness.panel.get_by_label("Task instruction").fill(case.instruction)
    await harness.panel.get_by_role("button", name="Send task").click()
    deadline = asyncio.get_running_loop().time() + 75
    while asyncio.get_running_loop().time() < deadline:
        session = harness.service.runtime_session
        if session is not None and session.get("status") in {"completed", "failed"}:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"Mode C timed out: {case.name}")
    session = harness.service.runtime_session
    assert session is not None and session.get("status") == "completed", (
        case.name,
        session,
        f"reasoner_calls={reasoner.calls}",
        reasoner.last_error,
        reasoner.context_trace,
        failure_trace,
        [
            (event.get("type"), event.get("summary"), event.get("phase"))
            for event in _timeline_events(harness.service)[-12:]
        ],
    )
    gold_c = await _gold_from_snapshot(harness.browser, case, base_url=base_url)
    assert gold_c, (
        f"Mode C failed independent fixture gold: {case.name}; "
        f"{await _gold_diagnostic(harness.browser, case)}"
    )
    assert reasoner.calls <= 24, f"Mode C exceeded the decision-call bound: {case.name}"
    if case.name == "ten_action_journey":
        events = _timeline_events(harness.service)
        completed = [event for event in events if event.get("type") == "ActionCompleted"]
        assert len(completed) >= 10

    assert status_a == status_b == "completed"
    assert gold_a and gold_b and gold_c
    assert steps_a == steps_b, (case.name, steps_a, steps_b)
    if case.name == "ten_action_journey":
        assert steps_a >= 10 and steps_b >= 10
