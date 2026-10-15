"""Consequential non-form buttons wait for approval in real Chromium."""

from pathlib import Path

import pytest

from browser_agent import AgentDecision, BrowserAction, BrowserSession, ElementRef
from browser_agent._types import SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentConfig, AgentRuntime

_FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/task_mix/reservation.html"


def _neutral_reservation_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "reservation.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
  <body>
    <main>
      <p role="status">No reservation submitted.</p>
      <button
        type="button"
        onclick="
          document.querySelector('[role=status]').textContent =
            'Reservation submitted for Seat 12A.';
        "
      >Continue</button>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )
    return fixture


def _reservation_status(snapshot: SemanticSnapshot) -> str:
    status = next(item for item in snapshot.elements if item.role == "status")
    return status.text or ""


class _ReservationAgent(Agent):
    def __init__(self, target_name: str) -> None:
        self.target_name = target_name

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if _reservation_status(snapshot).startswith("Reservation submitted for"):
            return AgentDecision(done=True, result_summary="Local reservation fixture changed.")
        target = next(
            item for item in snapshot.elements if item.accessible_name == self.target_name
        )
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(ref=target.ref, id=target.id, generation=target.generation),
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("neutral_control", "target_name", "goal", "confirm_high_risk"),
    [
        (False, "Reserve this seat", "Ask me before reserving this seat.", True),
        (
            True,
            "Continue",
            "Get my confirmation before reserving this seat.",
            False,
        ),
    ],
)
async def test_reservation_denial_prevents_non_submit_click(
    tmp_path: Path,
    neutral_control: bool,
    target_name: str,
    goal: str,
    confirm_high_risk: bool,
) -> None:
    async with BrowserSession.launch() as browser:
        fixture = _neutral_reservation_fixture(tmp_path) if neutral_control else _FIXTURE
        await browser.navigate(fixture.as_uri())
        runtime = AgentRuntime(
            _ReservationAgent(target_name),
            browser,
            config=AgentConfig(confirm_high_risk=confirm_high_risk),
        )
        pending = await runtime.run(goal, run_id="reservation-deny")
        assert pending.status == "pending_confirmation"
        assert _reservation_status(await browser.observe()) == "No reservation submitted."
        details = await runtime.pending_confirmation_details("reservation-deny")
        assert details["target"] == target_name
        denied = await runtime.resume_with_confirmation("reservation-deny", approved=False)
        assert denied.status == "failed"
        assert _reservation_status(await browser.observe()) == "No reservation submitted."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("neutral_control", "target_name", "goal", "confirm_high_risk"),
    [
        (False, "Reserve this seat", "Ask me before reserving this seat.", True),
        (
            True,
            "Continue",
            "Get my confirmation before reserving this seat.",
            False,
        ),
    ],
)
async def test_reservation_executes_only_after_explicit_approval(
    tmp_path: Path,
    neutral_control: bool,
    target_name: str,
    goal: str,
    confirm_high_risk: bool,
) -> None:
    async with BrowserSession.launch() as browser:
        fixture = _neutral_reservation_fixture(tmp_path) if neutral_control else _FIXTURE
        await browser.navigate(fixture.as_uri())
        runtime = AgentRuntime(
            _ReservationAgent(target_name),
            browser,
            config=AgentConfig(confirm_high_risk=confirm_high_risk),
        )
        pending = await runtime.run(goal, run_id="reservation-approve")
        assert pending.status == "pending_confirmation"
        assert _reservation_status(await browser.observe()) == "No reservation submitted."
        completed = await runtime.resume_with_confirmation("reservation-approve", approved=True)
        assert completed.done
        assert completed.status == "completed"
        assert _reservation_status(await browser.observe()).startswith("Reservation submitted for")


@pytest.mark.asyncio
async def test_approval_of_an_earlier_action_does_not_approve_the_next_action(
    tmp_path: Path,
) -> None:
    fixture = _neutral_reservation_fixture(tmp_path)
    async with BrowserSession.launch() as browser:
        await browser.navigate(fixture.as_uri())

        # This agent repeatedly selects the same neutral control. Each proposed
        # mutation must receive its own approval despite the first receipt.
        class RepeatingAgent(_ReservationAgent):
            async def decide(
                self,
                snapshot: SemanticSnapshot,
                task: TaskState,
                memory: WorkingMemory,
            ) -> AgentDecision:
                target = next(
                    item for item in snapshot.elements if item.accessible_name == "Continue"
                )
                return AgentDecision(
                    action=BrowserAction(
                        type="click",
                        target=ElementRef(
                            ref=target.ref, id=target.id, generation=target.generation
                        ),
                    )
                )

        runtime = AgentRuntime(
            RepeatingAgent("Continue"),
            browser,
            config=AgentConfig(confirm_high_risk=False, max_llm_calls=4),
        )
        pending = await runtime.run(
            "Get my confirmation before reserving this seat.", run_id="two-approvals"
        )
        assert pending.status == "pending_confirmation"
        second = await runtime.resume_with_confirmation("two-approvals", approved=True)
        assert second.status == "pending_confirmation"
        denied = await runtime.resume_with_confirmation("two-approvals", approved=False)
        assert denied.status == "failed"
        assert denied.steps_taken == 1
