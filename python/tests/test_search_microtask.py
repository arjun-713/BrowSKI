"""Complete search microtasks require task text and unique observed controls."""

from browser_agent._types import AgentObservation, PrunedElement, TaskState
from browser_agent.agent.microtasks import grounded_microtask


def _observation(*elements: PrunedElement) -> AgentObservation:
    return AgentObservation(
        url="https://shop.example/",
        title="Shop",
        state_generation=3,
        elements=list(elements),
    )


def _searchbox(ref: str = "@search", **updates: object) -> PrunedElement:
    values: dict[str, object] = {
        "ref": ref,
        "role": "searchbox",
        "name": "Search products",
        "interactable": True,
    }
    values.update(updates)
    return PrunedElement.model_validate(values)


def _search_button(ref: str = "@search-button", **updates: object) -> PrunedElement:
    values: dict[str, object] = {
        "ref": ref,
        "role": "button",
        "name": "Search",
        "interactable": True,
    }
    values.update(updates)
    return PrunedElement.model_validate(values)


def test_standalone_search_plans_task_topic_then_verified_search_click() -> None:
    goal = "Search for screen reader labels."
    plan = grounded_microtask(
        TaskState(task=goal),
        _observation(_searchbox(), _search_button(name="  SEARCH  ")),
    )

    assert plan is not None
    assert [(command.kind, command.ref, command.value) for command in plan.commands] == [
        ("type", "@search", "screen reader labels"),
        ("click", "@search-button", None),
    ]
    assert plan.commands[0].evidence == "field_matches_task:@search"
    assert plan.commands[1].evidence == "verified_action:click:@search-button"


def test_search_uses_the_same_authorized_query_as_candidate_construction() -> None:
    goal = "Search for noise cancelling headphones."
    plan = grounded_microtask(
        TaskState(task=goal),
        _observation(
            _searchbox(name="Search headphones"),
            _search_button(),
        ),
    )

    assert plan is not None
    assert plan.commands[0].value == "noise cancelling"


def test_search_button_can_share_the_grounded_fields_explicit_search_label() -> None:
    plan = grounded_microtask(
        TaskState(task="Search for insulated jackets."),
        _observation(_searchbox(name="Search catalog"), _search_button(name="Search catalog")),
    )
    assert plan is not None
    assert plan.commands[1].label == "Search catalog"

    assert (
        grounded_microtask(
            TaskState(task="Search for insulated jackets."),
            _observation(_searchbox(name="Search catalog"), _search_button(name="Search archive")),
        )
        is None
    )


def test_search_requires_unique_eligible_field_and_unique_enabled_button() -> None:
    goal = "Search for screen reader labels"
    assert (
        grounded_microtask(
            TaskState(task=goal),
            _observation(_searchbox(), _searchbox("@other"), _search_button()),
        )
        is None
    )
    assert (
        grounded_microtask(
            TaskState(task=goal),
            _observation(_searchbox(), _search_button(), _search_button("@other")),
        )
        is None
    )
    assert (
        grounded_microtask(
            TaskState(task=goal),
            _observation(_searchbox()),
        )
        is None
    )
    assert (
        grounded_microtask(
            TaskState(task=goal),
            _observation(_searchbox(), _search_button(state=["disabled"])),
        )
        is None
    )


def test_search_rejects_sensitive_or_non_interactable_fields() -> None:
    goal = "Search for access token"
    assert (
        grounded_microtask(
            TaskState(task=goal),
            _observation(
                _searchbox(name="Search password"),
                _search_button(),
            ),
        )
        is None
    )
    assert (
        grounded_microtask(
            TaskState(task="Search for screen reader labels"),
            _observation(_searchbox(interactable=False), _search_button()),
        )
        is None
    )


def test_search_microtask_rejects_extra_clauses_and_constraints() -> None:
    for goal in (
        "Search for screen reader labels and sort by date",
        "Search for screen reader labels on the homepage",
        "Search for screen reader labels. Click Search",
    ):
        assert (
            grounded_microtask(
                TaskState(task=goal),
                _observation(_searchbox(), _search_button()),
            )
            is None
        )
