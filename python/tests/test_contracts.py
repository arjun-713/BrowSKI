"""Contract tests: pydantic schemas behave (bounded memory, stagnation)."""

from browser_agent import (
    AgentObservation,
    PrunedElement,
    SnapshotDelta,
    TaskState,
    VisibilityClass,
    WorkingMemory,
)
from browser_agent._types import FailureKind
from browser_agent.progress.task_state import StagnationDetector
from browser_agent.providers import ProviderCapabilities, describe
from browser_agent.recovery.high_level import RecoveryPolicy
from browser_agent.tools.registry import ToolRegistry, ToolSpec


def test_working_memory_is_bounded() -> None:
    mem = WorkingMemory(max_events=3)
    for i in range(10):
        mem.record_event(f"event-{i}")
    assert len(mem.recent_events) == 3
    assert mem.recent_events[-1] == "event-9"
    mem.remember_fact("user", "alice")
    assert mem.facts["user"] == "alice"


def test_stagnation_detector() -> None:
    det = StagnationDetector(window=3)
    assert not det.is_stagnant
    det.observe("a")
    det.observe("a")
    assert not det.is_stagnant
    det.observe("a")
    assert det.is_stagnant
    det.observe("b")
    assert not det.is_stagnant
    det.reset()
    assert not det.is_stagnant


def test_task_state_defaults() -> None:
    task = TaskState(task="Find internships")
    assert not task.done
    assert task.steps_taken == 0


def test_provider_capabilities_describe() -> None:
    cap = ProviderCapabilities(multimodal=True, tool_calling=True)
    text = describe(cap)
    assert "multimodal=True" in text


def test_recovery_policy_escalates_after_bound() -> None:
    policy = RecoveryPolicy(max_replans=2)
    first = policy.decide(FailureKind.NAVIGATION, 0)
    assert first.decision == "replan"
    last = policy.decide(FailureKind.NAVIGATION, 2)
    assert last.decision == "escalate"


def test_tool_registry_rejects_duplicates() -> None:
    import pytest

    reg = ToolRegistry()
    reg.register(ToolSpec(name="navigate", description="Go to a URL"))
    assert reg.names() == ["navigate"]
    with pytest.raises(ValueError):
        reg.register(ToolSpec(name="navigate", description="dup"))
    schemas = reg.openai_schemas()
    assert schemas[0]["function"]["name"] == "navigate"


def test_m2_models_parse_full_snapshot() -> None:
    from browser_agent import SemanticSnapshot

    snap = SemanticSnapshot.model_validate(
        {
            "url": "https://x/",
            "title": "T",
            "active_tab": "tab-1",
            "viewport": {"width": 1280.0, "height": 800.0, "device_scale_factor": 1.0},
            "elements": [
                {
                    "id": 3,
                    "ref": "@email",
                    "generation": 2,
                    "role": "textbox",
                    "accessible_name": "Email",
                    "visibility": "VISIBLE",
                    "enabled": True,
                    "interactable": True,
                    "frame_path": ["main"],
                    "semantic_kind": "text_input",
                    "doc_order": 4,
                    "ancestry": ["html", "body", "form"],
                    "fingerprint": "abc123",
                }
            ],
            "page_fingerprint": "pf",
            "state_generation": 2,
        }
    )
    el = snap.by_ref("@email")
    assert el is not None
    assert el.visibility == VisibilityClass.VISIBLE
    assert el.frame_path == ["main"]
    assert snap.by_ref("@missing") is None


def test_m2_delta_and_render() -> None:
    delta = SnapshotDelta(
        added=["@city"],
        changed=[],
        removed=[],
        moved=[],
        navigation_changed=False,
        focus_changed=False,
    )
    assert not delta.is_empty()
    assert SnapshotDelta().is_empty()

    obs = AgentObservation(
        url="https://x/",
        title="T",
        state_generation=2,
        page_fingerprint="pf",
        elements=[
            PrunedElement(
                ref="@email",
                role="textbox",
                name="Email",
                interactable=True,
            )
        ],
    )
    text = obs.render_text()
    assert "@email" in text
    assert "textbox" in text
