"""Local browser evidence without disclosing arbitrary form values to providers."""

from __future__ import annotations

import re

from browser_agent._types import (
    AgentObservation,
    PrunedElement,
    SemanticElement,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.decisions.candidates import CandidatePolicy
from browser_agent.decisions.task_recording import candidate_policy_for_recording
from browser_agent.decisions.task_values import candidate_policy_for_task_literals
from browser_agent.progress.link_evidence import required_link_open_checks

_TERMINAL_TEXT = re.compile(r'\b(?:finish|stop|until)\b[^"\r\n]{0,120}"([^"\r\n]{1,300})"', re.I)


def in_viewport(element: SemanticElement, snapshot: SemanticSnapshot) -> bool:
    """CSS visibility alone does not establish that offscreen content is visible."""
    if not element.visible:
        return False
    box = element.bbox
    if box is None or snapshot.viewport.width <= 0 or snapshot.viewport.height <= 0:
        return True
    return (
        box.width > 0
        and box.height > 0
        and box.x < snapshot.viewport.width
        and box.y < snapshot.viewport.height
        and box.x + box.width > 0
        and box.y + box.height > 0
    )


def visible_page_text(snapshot: SemanticSnapshot) -> str:
    parts: list[str] = []
    for element in snapshot.elements:
        if in_viewport(element, snapshot) and element.role.casefold() not in {
            "button",
            "link",
            "textbox",
            "searchbox",
            "combobox",
            "checkbox",
            "radio",
            "option",
            "switch",
        }:
            parts.extend((element.accessible_name or "", element.text or ""))
    # Some software fixtures supply text blocks only. With real positioned
    # elements, use the browser's layout evidence instead of an unpositioned dump.
    if not snapshot.elements:
        parts.extend(block.text for block in snapshot.text_blocks)
        parts.append(snapshot.text_excerpt or "")
    return "\n".join(parts)


def semantic_observation(snapshot: SemanticSnapshot) -> AgentObservation:
    """Keep browser-owned aliases and layout status; omit private field values."""
    return AgentObservation(
        url=snapshot.url,
        title=snapshot.title,
        active_tab=snapshot.active_tab,
        state_generation=snapshot.state_generation,
        page_fingerprint=snapshot.page_fingerprint,
        focused=snapshot.focused,
        elements=[
            PrunedElement(
                ref=element.ref,
                role=element.role,
                name=element.accessible_name,
                text=element.text,
                value=None,
                state=[
                    *element.state,
                    "in_viewport" if in_viewport(element, snapshot) else "outside_viewport",
                ],
                interactable=element.interactable and element.visible and element.enabled,
                parent_ref=_native_option_parent(element, snapshot),
                context=_row_context(element, snapshot),
            )
            for element in snapshot.elements
        ],
    )


def _row_context(element: SemanticElement, snapshot: SemanticSnapshot) -> str | None:
    if "li" not in element.ancestry:
        return None
    rows = [
        item
        for item in snapshot.elements
        if item.doc_order < element.doc_order
        and item.frame_path == element.frame_path
        and item.semantic_kind.value == "text"
        and item.text
        and item.ancestry == element.ancestry[:-1]
    ]
    return max(rows, key=lambda item: item.doc_order).text if rows else None


def _native_option_parent(element: SemanticElement, snapshot: SemanticSnapshot) -> str | None:
    """DOM order establishes native option ownership, including optgroups.

    Custom ARIA widgets lack this native ancestry proof and stay ungrouped.
    Browser collection sorts document order within each frame. An option is
    contained by its nearest preceding native select in that same frame.
    """
    if element.role != "option" or "select" not in element.ancestry:
        return None
    controls = [
        item
        for item in snapshot.elements
        if item.role == "combobox"
        and item.frame_path == element.frame_path
        and item.doc_order < element.doc_order
    ]
    return max(controls, key=lambda item: item.doc_order).ref if controls else None


def task_terminal_text(task: TaskState) -> list[str]:
    """Preserve explicit user-provided stop conditions independently of a plan."""
    return [match.group(1) for match in _TERMINAL_TEXT.finditer(task.user_goal or task.task)][:10]


def task_terminal_satisfied(task: TaskState, snapshot: SemanticSnapshot) -> bool:
    return all(visible_phrase_present(phrase, snapshot) for phrase in task_terminal_text(task))


def visible_phrase_present(phrase: str, snapshot: SemanticSnapshot) -> bool:
    """Control labels and a negated status are not evidence of its positive effect."""
    if not phrase.strip():
        return False
    for line in visible_page_text(snapshot).casefold().splitlines():
        for match in re.finditer(re.escape(phrase.strip().casefold()), line):
            prefix = re.split(r"[.;!?]", line[: match.start()])[-1]
            if not re.search(r"\b(?:no|not|never|haven't|hasn't|isn't|wasn't)\b", prefix):
                return True
    return False


def local_browser_checks(
    task: TaskState,
    snapshot: SemanticSnapshot,
    observation: AgentObservation,
    policy: CandidatePolicy | None = None,
) -> dict[str, bool]:
    """Expose match booleans, never the values of unrelated browser fields.

    An assignment can become evidence only when it is independently authorized
    by the user's task. Model-generated milestone prose does not authorize it.
    """
    policy = candidate_policy_for_task_literals(
        task.user_goal or task.task, observation, policy or CandidatePolicy()
    )
    checks: dict[str, bool] = {}
    for ref, expected in policy.values_by_ref.items():
        element = snapshot.by_ref(ref)
        checks[f"field_matches_task:{ref}"] = bool(
            element is not None and element.visible and element.value == expected
        )
    for ref, expected in policy.select_labels_by_ref.items():
        element = snapshot.by_ref(ref)
        checks[f"selection_matches_task:{ref}"] = bool(
            element is not None and element.visible and element.value in expected
        )
    for ref, expected in policy.select_values_by_ref.items():
        element = snapshot.by_ref(ref)
        checks[f"selection_matches_task:{ref}"] = bool(
            element is not None and element.visible and element.value in expected
        )
    for fact in task.deterministic_evidence[-30:]:
        if fact.startswith(("verified_action:", "owned_task_destination:")):
            checks[fact] = True
    for ref, expected in policy.checked_by_ref.items():
        element = snapshot.by_ref(ref)
        checks[f"checked_matches_task:{ref}"] = bool(
            element is not None and element.visible and ("checked" in element.state) == expected
        )
    goal = task.user_goal or task.task
    for match in re.finditer(r'\b(uncheck|check|enable|disable)\s+"([^"\r\n]{1,120})"', goal, re.I):
        expected = match.group(1).casefold() in {"check", "enable"}
        label = match.group(2).casefold()
        matches = [
            element
            for element in snapshot.elements
            if element.role in {"checkbox", "switch"}
            and (element.accessible_name or "").casefold() == label
        ]
        if len(matches) == 1:
            element = matches[0]
            checks[f"checked_matches_task:{element.ref}"] = (
                element.visible and ("checked" in element.state) == expected
            )
    for text in task_terminal_text(task):
        checks[f"visible_text:{text}"] = visible_phrase_present(text, snapshot)
    checks.update(required_link_open_checks(task, snapshot))
    return checks


def evidence_satisfied(
    evidence: str,
    task: TaskState,
    snapshot: SemanticSnapshot,
    checks: dict[str, bool],
) -> bool:
    if evidence.startswith("verified_action:click:"):
        ref = evidence.removeprefix("verified_action:click:")
        element = snapshot.by_ref(ref)
        replacement = (
            "checked_matches_task"
            if element is not None and element.role in {"checkbox", "switch", "radio"}
            else "selection_matches_task"
            if element is not None and element.role == "combobox"
            else None
        )
        key = f"{replacement}:{ref}" if replacement is not None else None
        if key is not None and key in checks:
            # Canonical checkbox/select actions are not clicks. Only a value
            # independently authorized by the user's task can establish this
            # alternative typed proof; generic toggles have no such check.
            return checks[key]
    prefixes = (
        "field_matches_task:",
        "selection_matches_task:",
        "checked_matches_task:",
        "verified_action:",
        "owned_task_destination:",
        "required_link_open:",
        "visible_text:",
    )
    # Some structured provider responses use AND for a conjunction. Accept
    # it only when every term is one of our closed evidence forms. Literal
    # visible text containing a semicolon or AND remains a single text check.
    parts = [part.strip() for part in re.split(r";|\s+AND\s+", evidence, flags=re.I)]
    if 1 < len(parts) <= 8 and all(part.startswith(prefixes) for part in parts):
        return all(evidence_satisfied(part, task, snapshot, checks) for part in parts)
    if evidence.startswith(prefixes[:-1]):
        return checks.get(evidence, False)
    if evidence.startswith("visible_text:"):
        phrase = evidence.removeprefix("visible_text:").strip()
        return visible_phrase_present(phrase, snapshot)
    # Preserve historical literal evidence for existing plans. Arbitrary form
    # values remain excluded; only rendered text and browser metadata are used.
    del task
    legacy_text = "\n".join(
        [snapshot.url, snapshot.title or "", visible_page_text(snapshot)]
    ).casefold()
    return bool(evidence.strip() and evidence.casefold() in legacy_text)


def complete_observed_milestones(
    task: TaskState,
    snapshot: SemanticSnapshot,
    checks: dict[str, bool],
) -> list[str]:
    completed: list[str] = []
    for milestone in task.required_milestones:
        if milestone in task.completed:
            continue
        evidence = task.milestone_evidence.get(milestone)
        if not evidence or not evidence_satisfied(evidence, task, snapshot, checks):
            break
        task.completed.append(milestone)
        completed.append(milestone)
    return completed


def advance_observed_milestones(
    task: TaskState, memory: WorkingMemory, snapshot: SemanticSnapshot
) -> list[str]:
    observation = semantic_observation(snapshot)
    policy = candidate_policy_for_recording(task, memory, snapshot, observation)
    checks = local_browser_checks(task, snapshot, observation, policy)
    completed = complete_observed_milestones(task, snapshot, checks)
    for milestone in completed:
        memory.complete_milestone(milestone)
    if task.required_milestones and task.current_subgoal in task.completed:
        remaining = [item for item in task.required_milestones if item not in task.completed]
        task.current_subgoal = remaining[0] if remaining else None
        task.next_milestone = remaining[1] if len(remaining) > 1 else None
        memory.current_subgoal = task.current_subgoal
        memory.next_milestone = task.next_milestone
    return completed
