"""Luna receives the task once and complete descriptions for each action."""

from browser_agent.agent.luna_candidates import candidate_options
from browser_agent.decisions import ActionCandidate, CandidateKind


def test_options_preserve_action_and_remove_repeated_task_context() -> None:
    candidates = [
        ActionCandidate(
            candidate_id="c01",
            kind=CandidateKind.BROWSER_ACTION,
            action_type="click",
            target_ref="@search",
            description="Task: Find laptops; subgoal: Search; action: click Search at @search",
            observed_generation=1,
        ),
        ActionCandidate(
            candidate_id="c02",
            kind=CandidateKind.BROWSER_ACTION,
            action_type="new_tab",
            url="https://shop.example/",
            description="Open the user-specified URL https://shop.example/ in a new owned tab.",
            observed_generation=1,
        ),
    ]
    assert candidate_options(candidates) == {
        "c01": "click Search at @search",
        "c02": "Open the user-specified URL https://shop.example/ in a new owned tab.",
    }
