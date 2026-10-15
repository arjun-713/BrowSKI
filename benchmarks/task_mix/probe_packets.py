"""Synthetic action packet primitives and stable corpus-order constants."""

from __future__ import annotations

from typing import Any

SEED = 20261012
TEMPLATE_VERSION = "explicit-command-v1"
PERMUTATION_IDS = ("canonical", "rotate", "reverse")
PERMUTED_CASE_IDS = {
    "probe-button-01",
    "probe-button-02",
    "probe-button-03",
    "probe-check-01",
    "probe-check-02",
    "probe-check-03",
    "probe-type-01",
    "probe-type-02",
    "probe-type-03",
    "probe-select-01",
    "probe-select-02",
    "probe-select-03",
}


def _element(
    ref: str,
    role: str,
    name: str,
    *,
    value: str | None = None,
    text: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    element: dict[str, Any] = {
        "ref": ref,
        "role": role,
        "name": name,
        "interactable": role
        in {"button", "link", "textbox", "searchbox", "combobox", "checkbox"},
    }
    if value is not None:
        element["value"] = value
    if text is not None:
        element["text"] = text
    if state is not None:
        element["state"] = state
    return element


def _action(
    candidate_id: str,
    description: str,
    *,
    kind: str,
    target: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "action_type": kind,
        "target_ref": target,
        "parameters": parameters or {},
        "description": description,
    }


def _make_case(
    case_id: str,
    family: str,
    task: str,
    elements: list[dict[str, Any]],
    correct: dict[str, Any] | None,
    distractors: list[dict[str, Any]],
    *,
    command_kind: str | None = None,
    command_label: str | None = None,
    command_checked: bool | None = None,
    prerequisite_case: bool = False,
) -> dict[str, Any]:
    in_scope = (
        correct is not None and command_kind is not None and command_label is not None
    )
    candidates = [
        correct
        or _action(
            "ACTION_A",
            "Perform the requested action despite insufficient authorization.",
            kind="click",
        ),
        *distractors[:2],
        _action(
            "ESCALATE_TO_REASONER",
            "Ask the reasoning provider to resolve ambiguity or missing information.",
            kind="escalate",
        ),
    ]
    candidates = [
        {**item, "candidate_id": f"ACTION_{index}"}
        for index, item in enumerate(candidates[:3], start=1)
    ] + [candidates[-1]]
    gold_candidate = (
        candidates[0]["candidate_id"] if in_scope else "ESCALATE_TO_REASONER"
    )
    candidate_ids = [item["candidate_id"] for item in candidates]
    rotations = [
        candidate_ids,
        candidate_ids[1:] + candidate_ids[:1],
        list(reversed(candidate_ids)),
    ]
    scoped_command = None
    if in_scope:
        scoped_command = {
            "kind": command_kind,
            "label": command_label,
            "checked": command_checked,
        }
    return {
        "case_id": case_id,
        "family": family,
        "difficulty": "small"
        if family in {"button", "checkbox", "type", "select"}
        else "medium",
        "task": task,
        "broad_state": {
            "task": task,
            "current_subgoal": "Perform the first user-requested operation safely.",
            "page": "Synthetic local fixture",
            "relevant_elements": elements,
            "constraints": [
                "Respect explicit order and stop when evidence is insufficient."
            ],
        },
        "broad_candidates": candidates,
        "gold_candidate": gold_candidate,
        "in_scope": in_scope,
        "scoped_command": scoped_command,
        "scoped_prerequisite_case": prerequisite_case,
        "position_probe": case_id in PERMUTED_CASE_IDS,
        "order_permutations": {
            name: order for name, order in zip(PERMUTATION_IDS, rotations, strict=True)
        },
    }
