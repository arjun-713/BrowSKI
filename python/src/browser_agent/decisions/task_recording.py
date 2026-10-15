"""Bounded cross-tab recording from explicitly requested visible page facts."""

from __future__ import annotations

from dataclasses import replace

from browser_agent._types import (
    AgentDecision,
    AgentObservation,
    AuthorizedTransferEvidence,
    SemanticElement,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.decisions.candidates import CandidatePolicy
from browser_agent.decisions.record_scope import scoped_definition_snapshot
from browser_agent.decisions.task_record_fields import (
    canonical_destination as _canonical_destination,
)
from browser_agent.decisions.task_record_fields import (
    definition_facts as _definition_facts,
)
from browser_agent.decisions.task_record_fields import (
    destination_field_allowed as _destination_field_allowed,
)
from browser_agent.decisions.task_record_fields import (
    explicit_record_request as _explicit_record_request,
)
from browser_agent.decisions.task_record_fields import (
    model_destination_label as _model_destination_label,
)
from browser_agent.decisions.task_record_fields import (
    named_text_facts as _named_text_facts,
)
from browser_agent.decisions.task_record_fields import (
    normalize as _normalize,
)
from browser_agent.decisions.task_record_fields import (
    observed_destination_labels as _observed_destination_labels,
)
from browser_agent.decisions.task_record_fields import (
    requested_labels as _requested_labels,
)
from browser_agent.decisions.task_record_fields import (
    safe_value as _safe_value,
)
from browser_agent.decisions.task_record_fields import (
    task_text as _task_text,
)
from browser_agent.decisions.task_record_fields import (
    unique_visible_ref as _unique_visible_ref,
)
from browser_agent.providers.privacy import (
    has_recognized_sensitive_content,
    has_recognized_sensitive_label,
)

_MAX_EVIDENCE_ENTRIES = 8


def setup_record_targets(
    task: TaskState | str,
    memory: WorkingMemory,
    snapshot: SemanticSnapshot,
) -> bool:
    """Register the initial destination only for explicit cross-page recording."""
    goal = _task_text(task)
    labels = _requested_labels(goal)
    eligible = (
        labels
        and _explicit_record_request(goal)
        and snapshot.active_tab is not None
        and snapshot.active_tab in snapshot.tabs
    )
    if not eligible:
        if memory.record_destination_tab_id is not None:
            memory.authorized_transfer_evidence.clear()
        memory.record_destination_tab_id = None
        memory.record_destination_labels = []
        return False

    destination = snapshot.active_tab
    if (
        memory.record_destination_tab_id is not None
        and memory.record_destination_tab_id in snapshot.tabs
        and memory.record_destination_labels
        and all(
            _destination_field_allowed(label, labels) for label in memory.record_destination_labels
        )
    ):
        return True
    if memory.record_destination_tab_id is not None:
        memory.authorized_transfer_evidence.clear()
        memory.record_destination_tab_id = None
        memory.record_destination_labels = []
        return False
    bound_labels = _observed_destination_labels(snapshot, labels)
    if not bound_labels:
        memory.record_destination_tab_id = None
        memory.record_destination_labels = []
        return False
    memory.record_destination_tab_id = destination
    memory.record_destination_labels = bound_labels
    return True


def capture_record_bundle(
    task: TaskState | str,
    memory: WorkingMemory,
    snapshot: SemanticSnapshot,
    decision: AgentDecision,
) -> int:
    """Capture a selected heading and unambiguous visible definitions.

    The decision contributes only its existing semantic ``evidence_ref``. All
    stored text is read from Rust-authored elements in the current snapshot.
    """
    destination_tab = memory.record_destination_tab_id
    source_tab = snapshot.active_tab
    action = decision.action
    labels = _requested_labels(_task_text(task))
    if (
        not labels
        or not _explicit_record_request(_task_text(task))
        or not memory.record_destination_labels
        or not all(
            _destination_field_allowed(label, labels) for label in memory.record_destination_labels
        )
        or destination_tab is None
        or destination_tab not in snapshot.tabs
        or source_tab is None
        or source_tab not in snapshot.tabs
        or source_tab == destination_tab
        or action is None
        or action.type != "activate_tab"
        or action.tab != destination_tab
        or decision.evidence_ref is None
    ):
        return 0

    heading = _unique_visible_ref(snapshot, decision.evidence_ref)
    if heading is None or heading.role.casefold() != "heading":
        return 0

    found: list[tuple[str, SemanticElement, str]] = []
    model_label = _model_destination_label(memory.record_destination_labels, labels)
    if model_label is not None:
        heading_value = _safe_value(heading.text)
        if heading_value is not None:
            found.append((model_label, heading, heading_value))

    scoped = scoped_definition_snapshot(snapshot, heading)
    found.extend(_definition_facts(scoped, labels, memory.record_destination_labels))
    found.extend(_named_text_facts(scoped, labels, memory.record_destination_labels))

    # A duplicate semantic label makes that field ambiguous; omit it entirely.
    counts: dict[str, int] = {}
    for label, _, _ in found:
        key = _normalize(label)
        counts[key] = counts.get(key, 0) + 1

    captured = 0
    for label, element, value in found:
        if counts[_normalize(label)] != 1:
            continue
        if has_recognized_sensitive_label(label) or has_recognized_sensitive_content(value):
            continue
        evidence = AuthorizedTransferEvidence(
            source_tab_id=source_tab,
            source_ref=element.ref,
            source_generation=snapshot.state_generation,
            source_label=element.accessible_name or label,
            destination_label=label,
            value=value,
        )
        memory.remember_authorized_transfer_evidence(evidence)
        captured += 1
    return captured


def candidate_policy_for_recording(
    task: TaskState | str,
    memory: WorkingMemory,
    snapshot: SemanticSnapshot,
    observation: AgentObservation,
    base_policy: CandidatePolicy | None = None,
) -> CandidatePolicy:
    """Bind only unique, requested, source-owned recorded values to inputs."""
    policy = base_policy or CandidatePolicy()
    labels = _requested_labels(_task_text(task))
    destination_tab = memory.record_destination_tab_id
    if (
        not labels
        or not _explicit_record_request(_task_text(task))
        or not memory.record_destination_labels
        or not all(
            _destination_field_allowed(label, labels) for label in memory.record_destination_labels
        )
        or destination_tab is None
        or snapshot.active_tab != destination_tab
        or destination_tab not in snapshot.tabs
    ):
        return policy

    evidence_by_label: dict[str, list[AuthorizedTransferEvidence]] = {}
    registered_labels = {
        _canonical_destination(label) for label in memory.record_destination_labels
    }
    for item in memory.authorized_transfer_evidence[-_MAX_EVIDENCE_ENTRIES:]:
        key = _canonical_destination(item.destination_label)
        if (
            key is None
            or key not in registered_labels
            or not _destination_field_allowed(item.destination_label, labels)
            or item.source_tab_id == destination_tab
            or item.source_tab_id not in snapshot.tabs
            or not item.source_ref.startswith("@")
            or not item.value.strip()
            or has_recognized_sensitive_label(item.source_label)
            or has_recognized_sensitive_label(item.destination_label)
            or has_recognized_sensitive_content(item.value)
        ):
            continue
        evidence_by_label.setdefault(key, []).append(item)

    values = dict(policy.values_by_ref)
    derived: dict[str, str] = {}
    for label, evidence in evidence_by_label.items():
        if len(evidence) != 1:
            continue
        targets = [
            element
            for element in observation.elements
            if element.interactable
            and element.role.casefold() in {"textbox", "searchbox", "text input"}
            and element.name is not None
            and _canonical_destination(element.name) == label
        ]
        if len(targets) != 1 or targets[0].ref in values:
            continue
        derived[targets[0].ref] = evidence[0].value
    if not derived:
        return policy
    values.update(derived)
    return replace(policy, values_by_ref=values)
