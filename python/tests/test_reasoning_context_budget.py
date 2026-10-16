"""Large real-page inventories must fit without losing authorized targets."""

import pytest

from browser_agent._types import (
    AgentObservation,
    AuthorizedTransferEvidence,
    PrunedElement,
    TaskState,
    VerifiedLinkOpen,
    WorkingMemory,
)
from browser_agent.reasoning.context_budget import ContextBudgetExceeded, fit_observation_context
from browser_agent.reasoning.contracts import ReasoningContext, ReasoningPurpose


def large_context() -> ReasoningContext:
    return ReasoningContext(
        purpose=ReasoningPurpose.CHOOSE_ACTION,
        task=TaskState(task="Find the laptop. Do not buy it.", constraints=["Do not buy"]),
        memory=WorkingMemory(user_goal="Find the laptop"),
        observation=AgentObservation(
            url="https://example.test/",
            state_generation=9,
            page_fingerprint="stable-page",
            focused="@focus",
            elements=[
                PrunedElement(ref=f"@noise-{index}", role="text", text="Navigation " * 40)
                for index in range(440)
            ]
            + [
                PrunedElement(ref="@form", role="form", name="Search form"),
                PrunedElement(ref="@search", role="searchbox", name="Search", parent_ref="@form"),
                PrunedElement(ref="@focus", role="button", name="Focused control"),
            ],
        ),
        candidate_options={"c01": "Type the task query into @search", "c02": "Escalate"},
        browser_checks={"purchase_confirmed": False},
    )


def test_large_observation_preserves_candidates_parents_focus_and_policy() -> None:
    original = large_context()
    before = original.model_dump_json()
    bounded = fit_observation_context(original, max_characters=32_000)

    assert len(bounded.model_dump_json(exclude_none=True)) <= 32_000
    assert bounded.observation.truncated
    refs = {element.ref for element in bounded.observation.elements}
    assert {"@search", "@form", "@focus"} <= refs
    assert len(refs) < len(original.observation.elements)
    assert bounded.task == original.task
    assert bounded.memory == original.memory
    assert bounded.candidate_options == original.candidate_options
    assert bounded.browser_checks == original.browser_checks
    assert bounded.observation.state_generation == 9
    originals = {element.ref: element for element in original.observation.elements}
    assert all(element == originals[element.ref] for element in bounded.observation.elements)
    assert original.model_dump_json() == before


def test_required_task_data_is_never_truncated_to_force_a_request() -> None:
    context = large_context().model_copy(update={"task": TaskState(task="constraint " * 4000)})
    with pytest.raises(ContextBudgetExceeded, match="Required task context"):
        fit_observation_context(context, max_characters=32_000)


def test_required_target_is_never_discarded_to_force_a_request() -> None:
    context = large_context()
    context.observation.elements[-2].context = "Required row context " * 4000
    with pytest.raises(ContextBudgetExceeded, match="Required candidate context"):
        fit_observation_context(context, max_characters=32_000)


def test_small_context_is_preserved_without_projection() -> None:
    context = large_context()
    context.observation.elements = context.observation.elements[-3:]
    assert fit_observation_context(context, max_characters=32_000) is context


def test_typed_targets_and_source_evidence_survive_projection() -> None:
    context = large_context().model_copy(
        update={
            "candidate_options": {"c01": "Use the selected search field"},
            "required_observation_refs": ("@search",),
        }
    )
    context.memory.authorized_transfer_evidence.append(
        AuthorizedTransferEvidence(
            source_tab_id="tab-1",
            source_ref="@noise-439",
            source_generation=9,
            source_label="Reference",
            destination_label="Reference field",
            value="catalogue-reference",
        )
    )
    context.task.verified_link_opens.append(
        VerifiedLinkOpen(
            source_tab_id="tab-1",
            source_ref="@noise-438",
            source_generation=9,
            source_page_fingerprint="stable-page",
            opened_tab_id="tab-2",
        )
    )

    bounded = fit_observation_context(context, max_characters=32_000)

    refs = {item.ref for item in bounded.observation.elements}
    assert {"@search", "@form", "@noise-439", "@noise-438"} <= refs
    assert "required_observation_refs" not in bounded.model_dump()
