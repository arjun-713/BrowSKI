"""Native option grouping follows Rust document order within each frame."""

from test_microtask_call_budget import ScriptedReasoningProvider

from browser_agent._types import SemanticElement, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.progress.evidence import semantic_observation
from browser_agent.reasoning import ReasoningDecision, ReasoningOutcome


def element(ref: str, role: str, order: int, frame: str = "main") -> SemanticElement:
    return SemanticElement(
        ref=ref,
        role=role,
        doc_order=order,
        frame_path=[frame],
        ancestry=["html", "body", "select"] if role == "option" else ["html", "body"],
        accessible_name="3:00 PM" if role == "option" else ref.removeprefix("@"),
        fingerprint=ref,
    )


def test_native_options_belong_to_preceding_select_in_same_frame() -> None:
    page = SemanticSnapshot(
        url="https://fixture.test/",
        state_generation=1,
        page_fingerprint="option-parent-test",
        elements=[
            element("@starts", "combobox", 1),
            element("@3_pm", "option", 2),
            element("@foreign", "combobox", 3, "foreign"),
            element("@ends", "combobox", 4),
            element("@3_pm_2", "option", 5),
        ],
    )
    observation = semantic_observation(page)
    assert observation.elements[1].parent_ref == "@starts"
    assert observation.elements[4].parent_ref == "@ends"


def test_custom_option_without_native_ancestry_is_not_assumed_to_belong_to_select() -> None:
    option = element("@custom", "option", 2)
    option.ancestry = ["html", "body", "div"]
    page = SemanticSnapshot(
        url="https://fixture.test/",
        state_generation=1,
        page_fingerprint="custom-option-test",
        elements=[element("@starts", "combobox", 1), option],
    )
    assert semantic_observation(page).elements[1].parent_ref is None


async def test_person_color_name_does_not_require_vision() -> None:
    page = SemanticSnapshot(
        url="https://fixture.test/",
        state_generation=1,
        page_fingerprint="color-name-test",
        elements=[element("@full_name", "textbox", 1)],
    )
    provider = ScriptedReasoningProvider(
        ReasoningDecision(outcome=ReasoningOutcome.ASK_USER, questions=["Ready for details?"])
    )
    agent = LunaDecisionAgent(None, provider)
    await agent.decide(
        page,
        TaskState(task="Register Alex Green for the workshop."),
        WorkingMemory(),
    )
    assert len(provider.calls) == 1
    visual = await agent.decide(page, TaskState(task="Click the green button."), WorkingMemory())
    assert visual.ask_user
    assert "vision" in " ".join(visual.ask_user).casefold()
    assert len(provider.calls) == 1
