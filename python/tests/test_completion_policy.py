"""A model plan cannot omit user-authorized fields or confirmation."""

from browser_agent._types import (
    SemanticElement,
    SemanticSnapshot,
    TaskState,
    VerifiedLinkOpen,
    WorkingMemory,
)
from browser_agent.agent.graph import validate_completion_proposal
from browser_agent.progress.completion_policy import (
    outstanding_constraints,
    record_required_link_open,
    register_requested_links,
    requests_confirmation,
    required_link_open_checks,
)


def page(*elements: SemanticElement) -> SemanticSnapshot:
    return SemanticSnapshot(
        url="https://fixture.test/",
        page_fingerprint="completion-constraints",
        state_generation=1,
        active_tab="main",
        tabs=["main"],
        elements=list(elements),
    )


def test_omitted_checkbox_assignment_still_prevents_completion() -> None:
    checkbox = SemanticElement(
        ref="@updates",
        role="checkbox",
        accessible_name="Weekly digest",
        state=[],
        fingerprint="updates",
    )
    task = TaskState(task="Enable weekly digest.")
    assert outstanding_constraints(task, WorkingMemory(), page(checkbox)) == [
        "checked_matches_task:@updates"
    ]
    checkbox.state = ["checked"]
    assert outstanding_constraints(task, WorkingMemory(), page(checkbox)) == []


def test_confirmation_is_required_until_the_user_approves() -> None:
    task = TaskState(task="Prepare the booking, but get my confirmation before reserving.")
    assert requests_confirmation(task)
    assert outstanding_constraints(task, WorkingMemory(), page())
    task.confirmation_received = True
    assert not requests_confirmation(task)
    assert outstanding_constraints(task, WorkingMemory(), page()) == []


def test_completion_proposal_cannot_override_pending_confirmation() -> None:
    milestone = "Finalize the workflow."
    task = TaskState(
        task="Complete the workflow and get my confirmation before finalizing.",
        plan_initialized=True,
        milestones=[milestone],
        required_milestones=[milestone],
        milestone_evidence={milestone: "visible_text:Workflow ready"},
    )
    snapshot = page(
        SemanticElement(ref="@status", role="status", text="Workflow ready", fingerprint="status")
    )

    accepted, _ = validate_completion_proposal(
        task, WorkingMemory(), snapshot, verified_action=True
    )

    assert not accepted


def test_completion_proposal_cannot_omit_a_user_requested_field_value() -> None:
    milestone = "Finish the workflow."
    task = TaskState(
        task="Enable weekly digest and finish the workflow.",
        plan_initialized=True,
        milestones=[milestone],
        required_milestones=[milestone],
        milestone_evidence={milestone: "visible_text:Workflow ready"},
    )
    snapshot = page(
        SemanticElement(
            ref="@updates",
            role="checkbox",
            accessible_name="Weekly digest",
            state=[],
            fingerprint="updates",
        ),
        SemanticElement(ref="@status", role="status", text="Workflow ready", fingerprint="status"),
    )

    accepted, pending = validate_completion_proposal(
        task, WorkingMemory(), snapshot, verified_action=True
    )

    assert not accepted
    assert "checked_matches_task:@updates" in pending


def test_completion_proposal_cannot_omit_a_required_link_open() -> None:
    milestone = "Finish the research."
    task = TaskState(
        task="Open each product link in its own tab and finish the research.",
        plan_initialized=True,
        milestones=[milestone],
        required_milestones=[milestone],
        milestone_evidence={milestone: "visible_text:Research ready"},
        required_link_refs=["@product"],
        required_link_source_tab_id="main",
        required_link_source_generation=1,
        required_link_source_fingerprint="completion-constraints",
    )
    snapshot = page(
        SemanticElement(
            ref="@product",
            role="link",
            accessible_name="Product details",
            fingerprint="product",
        ),
        SemanticElement(ref="@status", role="status", text="Research ready", fingerprint="status"),
    )

    accepted, pending = validate_completion_proposal(
        task, WorkingMemory(), snapshot, verified_action=True
    )

    assert not accepted
    assert "required_link_open:@product" in pending


def test_completion_proposal_keeps_previously_completed_milestones() -> None:
    first = "Open the workflow page."
    second = "Save the workflow."
    task = TaskState(
        task="Save the workflow.",
        plan_initialized=True,
        milestones=[first, second],
        required_milestones=[first, second],
        completed=[first],
        milestone_evidence={
            first: "visible_text:Workflow page",
            second: "visible_text:Workflow saved",
        },
    )
    snapshot = page(
        SemanticElement(
            ref="@status",
            role="status",
            text="Workflow page\nWorkflow saved",
            fingerprint="status",
        )
    )
    memory = WorkingMemory(completed_milestones=[first])

    accepted, _ = validate_completion_proposal(task, memory, snapshot, verified_action=True)

    assert accepted
    assert task.completed == [first, second]
    assert memory.completed_milestones == [first, second]


def test_link_group_requires_each_requested_click_proof() -> None:
    links = [
        SemanticElement(
            ref=f"@details_{index}",
            role="link",
            accessible_name=f"Model {index} details",
            fingerprint=f"link-{index}",
        )
        for index in range(3)
    ]
    task = TaskState(task="Open each product details link in its own tab.")
    current = page(*links)
    register_requested_links(task, current)
    assert task.required_link_refs == [item.ref for item in links]
    task.verified_link_opens = [
        VerifiedLinkOpen(
            source_tab_id="main",
            source_ref="@details_0",
            source_generation=1,
            source_page_fingerprint="completion-constraints",
            opened_tab_id="details-tab-0",
            link_label="Model 0 details",
        )
    ]
    current.tabs.append("details-tab-0")
    assert required_link_open_checks(task, current) == {
        "required_link_open:@details_0": True,
        "required_link_open:@details_1": False,
        "required_link_open:@details_2": False,
    }
    assert outstanding_constraints(task, WorkingMemory(), current) == [
        "required_link_open:@details_1",
        "required_link_open:@details_2",
    ]


def test_requested_links_are_bounded_and_require_exactly_one_new_tab_to_prove() -> None:
    links = [
        SemanticElement(
            ref=f"@product_{index}",
            role="link",
            accessible_name=f"Product {index}",
            fingerprint=f"product-{index}",
        )
        for index in range(9)
    ]
    task = TaskState(task="Open every product link in separate tabs.")
    register_requested_links(task, page(*links))
    assert task.required_link_refs == []


def test_link_open_proof_binds_source_identity_and_one_new_owned_tab() -> None:
    link = SemanticElement(
        ref="@product",
        role="link",
        accessible_name="Product details",
        fingerprint="product-link",
    )
    before = page(link)
    task = TaskState(task="Open every product link in separate tabs.")
    register_requested_links(task, before)
    action = {"type": "click", "target": {"ref": "@product", "generation": 1}}

    proof = record_required_link_open(
        task,
        before,
        before.model_copy(update={"tabs": ["main", "product-tab"]}),
        action,
    )

    assert proof is not None
    assert proof.source_tab_id == "main"
    assert proof.source_ref == "@product"
    assert proof.opened_tab_id == "product-tab"
    assert proof.link_label == "Product details"
    assert (
        record_required_link_open(
            task,
            before,
            before.model_copy(update={"tabs": ["main", "one", "two"]}),
            action,
        )
        is None
    )
    assert (
        record_required_link_open(
            task,
            before.model_copy(update={"active_tab": "other"}),
            before.model_copy(update={"tabs": ["main", "product-tab"]}),
            action,
        )
        is None
    )


def test_general_find_request_does_not_require_an_optional_search_route() -> None:
    search = SemanticElement(
        ref="@search",
        role="searchbox",
        accessible_name="Search",
        value="",
        fingerprint="search",
    )
    assert (
        outstanding_constraints(TaskState(task="Find a laptop."), WorkingMemory(), page(search))
        == []
    )
    assert outstanding_constraints(
        TaskState(task="Search for a laptop."), WorkingMemory(), page(search)
    ) == ["field_matches_task:@search"]
