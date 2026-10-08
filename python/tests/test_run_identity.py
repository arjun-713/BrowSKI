from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

from browser_agent import BrowserSession
from browser_agent._types import AgentDecision, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentRuntime
from browser_agent.persistence.run_identity import new_run_id, resolve_run_id, validate_run_id


@pytest.mark.parametrize(
    "value",
    [
        "trace-run",
        "runtime_restart-7",
        "A" * 64,
        "d61513ce-f840-4265-a775-9b8766a440f3",
    ],
)
def test_validate_run_id_preserves_bounded_m7_ids(value: str) -> None:
    assert validate_run_id(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "complete the checkout",
        "run/../../sensitive",
        "contains\nnewline",
        "A" * 65,
        42,
        None,
    ],
)
def test_validate_run_id_rejects_unbounded_or_free_form_input_without_echo(
    value: object,
) -> None:
    with pytest.raises(ValueError) as error:
        validate_run_id(value)

    message = str(error.value)
    assert "non-sensitive slug" in message
    if isinstance(value, str) and value:
        assert value not in message


def test_resolve_run_id_generates_uuid_only_when_absent() -> None:
    generated = resolve_run_id(None)

    assert str(uuid.UUID(generated)) == generated
    assert resolve_run_id("resume-me") == "resume-me"
    assert str(uuid.UUID(new_run_id()))


def test_secret_looking_but_syntactically_valid_ids_are_not_secret_scanned() -> None:
    # Slug validation is a bounded identifier contract, not universal DLP.
    assert validate_run_id("sk-example-token-within-slug-bounds") == (
        "sk-example-token-within-slug-bounds"
    )


class _UnusedAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = snapshot, task, memory
        raise AssertionError("invalid run IDs must be rejected before agent execution")


def _unused_graph(*args: Any, **kwargs: Any) -> Any:
    _ = args, kwargs
    return object()


@pytest.mark.asyncio
async def test_runtime_rejects_free_form_run_id_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import browser_agent.agent.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "build_agent_graph", _unused_graph)
    runtime = AgentRuntime(_UnusedAgent(), cast(BrowserSession, object()))
    marker = "private task marker that must not be used as a run identifier"

    with pytest.raises(ValueError) as error:
        await runtime.run("A harmless task", run_id=marker)

    assert marker not in str(error.value)


@pytest.mark.asyncio
async def test_runtime_run_control_validates_ids_before_graph_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import browser_agent.agent.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "build_agent_graph", _unused_graph)
    runtime = AgentRuntime(_UnusedAgent(), cast(BrowserSession, object()))
    marker = "private control marker that must not be an ID"

    with pytest.raises(ValueError) as pause_error:
        runtime.pause(marker)
    with pytest.raises(ValueError) as stop_error:
        await runtime.stop(marker)
    with pytest.raises(ValueError) as resume_error:
        await runtime.resume(marker)
    with pytest.raises(ValueError) as approval_error:
        await runtime.resume_with_confirmation(marker, approved=True)
    with pytest.raises(ValueError) as details_error:
        await runtime.pending_confirmation_details(marker)

    assert all(
        marker not in str(error.value)
        for error in (pause_error, stop_error, resume_error, approval_error, details_error)
    )
