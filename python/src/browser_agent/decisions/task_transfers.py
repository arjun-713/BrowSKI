"""Explicit, finite cross-tab transfers from currently visible semantic text."""

from __future__ import annotations

import re
import unicodedata
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
from browser_agent.providers.privacy import (
    has_recognized_sensitive_content,
    has_recognized_sensitive_label,
)
from browser_agent.task_literals import quoted_transfer_labels

_MAX_VALUE_CHARS = 256
_MAX_EVIDENCE_ENTRIES = 8


def transfer_labels(task: str) -> tuple[str, str] | None:
    """Return the one bounded explicit transfer request, if it is unambiguous."""
    labels = quoted_transfer_labels(task)
    if labels is None:
        return None
    source, destination = labels
    if has_recognized_sensitive_label(source) or has_recognized_sensitive_label(destination):
        return None
    return source, destination


def record_transfer_evidence(
    task: TaskState,
    memory: WorkingMemory,
    snapshot: SemanticSnapshot,
    decision: AgentDecision,
) -> bool:
    """Record one explicitly requested visible text value from an owned tab.

    This never reads legacy ``acquired_facts`` and never accepts a value from
    the model. The model supplies only a semantic ref; the value is resolved
    from this current Rust snapshot after a finite action was accepted.
    """
    labels = transfer_labels(task.user_goal or task.task)
    if (
        labels is None
        or decision.action is None
        or decision.evidence_ref is None
        or snapshot.active_tab is None
        or snapshot.active_tab not in snapshot.tabs
    ):
        return False
    source_label, destination_label = labels
    source = _source_element(snapshot, decision.evidence_ref, source_label)
    if source is None:
        return False
    value = _value_for_source(source, source_label)
    if value is None or has_recognized_sensitive_content(value):
        return False
    evidence = AuthorizedTransferEvidence(
        source_tab_id=snapshot.active_tab,
        source_ref=source.ref,
        source_generation=snapshot.state_generation,
        source_label=source_label,
        destination_label=destination_label,
        value=value,
    )
    memory.remember_authorized_transfer_evidence(evidence)
    return True


def candidate_policy_for_authorized_transfers(
    task: str,
    memory: WorkingMemory,
    snapshot: SemanticSnapshot,
    observation: AgentObservation,
    base_policy: CandidatePolicy | None = None,
) -> CandidatePolicy:
    """Add only a unique explicit transfer value for a matching input label."""
    policy = base_policy or CandidatePolicy()
    labels = transfer_labels(task)
    if labels is None:
        return policy
    _, destination = labels
    destination_key = _normalize(destination)
    if not destination_key:
        return policy

    evidence = [
        item
        for item in memory.authorized_transfer_evidence[-_MAX_EVIDENCE_ENTRIES:]
        if _normalize(item.destination_label) == destination_key
        and item.source_tab_id != snapshot.active_tab
        and item.source_tab_id in snapshot.tabs
        and item.value.strip()
        and not has_recognized_sensitive_label(item.source_label)
        and not has_recognized_sensitive_label(item.destination_label)
        and not has_recognized_sensitive_content(item.value)
    ]
    if len(evidence) != 1:
        return policy
    value = evidence[0].value
    targets = [
        element
        for element in observation.elements
        if element.interactable
        and element.role.casefold() in {"textbox", "searchbox", "text input"}
        and element.name is not None
        and _normalize(element.name) == destination_key
    ]
    if len(targets) != 1 or targets[0].ref in policy.values_by_ref:
        return policy
    values = dict(policy.values_by_ref)
    values[targets[0].ref] = value
    return replace(policy, values_by_ref=values)


def _source_element(
    snapshot: SemanticSnapshot,
    ref: str,
    label: str,
) -> SemanticElement | None:
    if len(ref) > 200 or not ref.startswith("@"):
        return None
    matches = [
        element
        for element in snapshot.elements
        if element.ref == ref
        and element.visible
        and element.visibility.value == "VISIBLE"
        and element.enabled
        and not element.interactable
        and element.value is None
        and element.role.casefold()
        not in {"textbox", "searchbox", "text input", "password", "passwordbox", "credential"}
        and _normalize(element.accessible_name or "") == _normalize(label)
    ]
    return matches[0] if len(matches) == 1 else None


def _value_for_source(element: SemanticElement, label: str) -> str | None:
    if element.text is None:
        return None
    value = element.text.strip()
    if not value:
        return None
    # A named semantic text node may contain the value directly. For a combined
    # label/value node, require the exact label followed by a clear delimiter.
    if _normalize(value) == _normalize(label):
        return None
    prefix = re.match(r"^\s*" + re.escape(label) + r"\s*[:=–—-]\s*(.+?)\s*$", value, re.I)
    if prefix is not None:
        value = prefix.group(1).strip()
    if not value or len(value) > _MAX_VALUE_CHARS or any(ord(ch) < 32 for ch in value):
        return None
    return value


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
