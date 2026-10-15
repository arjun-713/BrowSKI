"""Candidate ranking reorders only authorized semantic targets."""

from browser_agent._types import (
    AgentObservation,
    PrunedElement,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.luna_candidates import action_candidates
from browser_agent.decisions.candidate_ranking import rank_observation_for_candidates
from browser_agent.decisions.candidates import CandidatePolicy, build_action_candidates
from browser_agent.decisions.task_values import candidate_policy_for_task_literals


def _shopping_observation() -> AgentObservation:
    return AgentObservation(
        url="https://shop.example/search",
        title="Search results",
        state_generation=4,
        elements=[
            PrunedElement(
                ref="@home",
                role="link",
                name="Home",
                interactable=True,
            ),
            PrunedElement(
                ref="@deals",
                role="button",
                name="Deals",
                interactable=True,
            ),
            PrunedElement(
                ref="@product",
                role="link",
                name="16GB 512GB Laptop",
                interactable=True,
            ),
            PrunedElement(
                ref="@search",
                role="searchbox",
                name="Search products",
                interactable=True,
            ),
        ],
    )


def test_search_action_ranks_ahead_of_unrelated_navigation_and_product_links() -> None:
    task = "Buy a 16GB 512GB laptop on the store"
    subgoal = "Search for 16GB 512GB laptop"
    observation = _shopping_observation()
    policy = candidate_policy_for_task_literals(task, observation)
    ordered = rank_observation_for_candidates(observation, task=task, current_subgoal=subgoal)
    candidates = build_action_candidates(task, subgoal, observation, {"click", "type"}, policy)
    ranked = build_action_candidates(task, subgoal, ordered, {"click", "type"}, policy)

    assert ranked[0].action_type == "type"
    assert ranked[0].target_ref == "@search"
    assert {candidate.candidate_id for candidate in ranked} == {
        candidate.candidate_id for candidate in candidates
    }
    assert {candidate.target_ref for candidate in ranked} == {
        candidate.target_ref for candidate in candidates
    }


def test_current_product_subgoal_ranks_the_matching_result_above_search_box() -> None:
    task = "Buy a 16GB 512GB laptop on the store"
    observation = _shopping_observation()
    policy = candidate_policy_for_task_literals(task, observation)
    ordered = rank_observation_for_candidates(
        observation, task=task, current_subgoal="Open the 16GB 512GB Laptop product listing"
    )
    ranked = build_action_candidates(
        task,
        "Open the 16GB 512GB Laptop product listing",
        ordered,
        {"click", "type"},
        policy,
    )

    assert ranked[0].action_type == "click"
    assert ranked[0].target_ref == "@product"


def test_candidate_ranking_is_stable_for_ties_and_does_not_mutate_candidates() -> None:
    task = "Complete a shopping task"
    observation = _shopping_observation()
    before = observation.model_copy(deep=True)
    ranked = rank_observation_for_candidates(
        observation, task=task, current_subgoal="Unknown next step"
    )
    assert ranked.elements == before.elements
    assert observation == before


def test_observation_ranking_keeps_a_relevant_control_beyond_navigation_cap() -> None:
    task = "Buy a 16GB 512GB laptop on the store"
    subgoal = "Open the 16GB 512GB Laptop product listing"
    observation = AgentObservation(
        url="https://shop.example/search",
        title="Search results",
        state_generation=4,
        elements=[
            PrunedElement(
                ref=f"@nav-{index}",
                role="link",
                name=f"Navigation item {index}",
                interactable=True,
            )
            for index in range(35)
        ]
        + [
            PrunedElement(
                ref="@target-laptop",
                role="link",
                name="16GB 512GB Laptop",
                interactable=True,
            )
        ],
    )

    ranked_observation = rank_observation_for_candidates(
        observation,
        task=task,
        current_subgoal=subgoal,
    )
    candidates = build_action_candidates(task, subgoal, ranked_observation, {"click"})

    assert ranked_observation.elements[0].ref == "@target-laptop"
    assert any(candidate.target_ref == "@target-laptop" for candidate in candidates)
    assert {element.ref for element in ranked_observation.elements} == {
        element.ref for element in observation.elements
    }


def test_observation_ranking_prioritizes_search_control_for_search_subgoal() -> None:
    task = "Buy a 16GB 512GB laptop on the store"
    observation = _shopping_observation()

    ranked = rank_observation_for_candidates(
        observation,
        task=task,
        current_subgoal=task,
    )

    assert ranked.elements[0].ref == "@search"


def test_list_item_context_ranks_the_action_for_the_pending_named_target() -> None:
    observation = AgentObservation(
        url="https://support.example/tickets",
        title="Accessibility tickets",
        elements=[
            PrunedElement(
                ref="@ticket-418",
                role="button",
                name="Open ticket 418",
                context="Keyboard shortcuts Ticket 418 Accessibility Open ticket 418",
                interactable=True,
            ),
            PrunedElement(
                ref="@ticket-442",
                role="button",
                name="Open ticket 442",
                context="Screen reader labels Ticket 442 Accessibility Open ticket 442",
                interactable=True,
            ),
        ],
    )

    ranked = rank_observation_for_candidates(
        observation,
        task="Pin the Keyboard shortcuts and Screen reader labels accessibility tickets.",
        current_subgoal="Open the Screen reader labels ticket",
    )

    assert ranked.elements[0].ref == "@ticket-442"


def test_candidate_assembly_ranks_against_the_next_pending_milestone() -> None:
    goal = "Pin the Keyboard shortcuts and Screen reader labels accessibility tickets."
    task = TaskState(task=goal, next_milestone="Open the Screen reader labels ticket")
    snapshot = SemanticSnapshot(
        url="https://support.example/tickets",
        active_tab="support-tab",
        tabs=["support-tab"],
        page_fingerprint="tickets",
        state_generation=1,
    )
    observation = AgentObservation(
        url=snapshot.url,
        active_tab="support-tab",
        elements=[
            PrunedElement(
                ref="@ticket-418",
                role="button",
                name="Open ticket 418",
                context="Keyboard shortcuts Ticket 418 Accessibility Open ticket 418",
            ),
            PrunedElement(
                ref="@ticket-442",
                role="button",
                name="Open ticket 442",
                context="Screen reader labels Ticket 442 Accessibility Open ticket 442",
            ),
        ],
    )

    candidates = action_candidates(
        snapshot=snapshot,
        task=task,
        memory=WorkingMemory(user_goal=goal),
        observation=observation,
        candidate_policy=CandidatePolicy(),
    )

    assert candidates
    assert candidates[0].target_ref == "@ticket-442"


def test_required_source_link_clicks_stop_at_owned_tab_limit() -> None:
    goal = "Open each product link in separate tabs."
    snapshot = SemanticSnapshot(
        url="https://shop.example/products",
        active_tab="tab-0",
        tabs=[f"tab-{index}" for index in range(8)],
        page_fingerprint="products",
        state_generation=3,
    )
    task = TaskState(
        task=goal,
        required_link_refs=["@product-a"],
        required_link_source_tab_id="tab-0",
        required_link_source_generation=3,
        required_link_source_fingerprint="products",
    )
    observation = AgentObservation(
        url=snapshot.url,
        active_tab=snapshot.active_tab,
        state_generation=snapshot.state_generation,
        elements=[
            PrunedElement(
                ref="@product-a",
                role="link",
                name="Product A",
                interactable=True,
            )
        ],
    )

    candidates = action_candidates(
        snapshot=snapshot,
        task=task,
        memory=WorkingMemory(user_goal=goal),
        observation=observation,
        candidate_policy=CandidatePolicy(),
    )

    assert all(candidate.target_ref != "@product-a" for candidate in candidates)
