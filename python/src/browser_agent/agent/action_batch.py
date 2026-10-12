"""Short lived, locally revalidated batches for same-page form actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from browser_agent._types import (
    AgentObservation,
    BrowserAction,
    PrunedElement,
    SemanticSnapshot,
)
from browser_agent.agent.interference import same_decision_state
from browser_agent.decisions.action_matching import actions_match
from browser_agent.reasoning.contracts import ReasoningAction

_BATCH_LIMIT = 4
_MUTATING_ACTIONS = {"type", "select", "check"}
_FORM_ACTIONS = _MUTATING_ACTIONS | {"click"}
_TAB_ACTIONS = {"new_tab"}


@dataclass(slots=True)
class PendingActionBatch:
    """Ephemeral state; do not checkpoint or serialize queued action values."""

    actions: tuple[ReasoningAction, ...]
    run_id: str
    page_id: str
    anchor: SemanticSnapshot
    next_index: int = 1
    previous_action: ReasoningAction | None = None

    def clear(self) -> None:
        """Drop all queued action values and the source snapshot from memory."""
        self.actions = ()
        self.anchor = SemanticSnapshot(
            url="",
            page_fingerprint="",
            state_generation=0,
        )
        self.previous_action = None
        self.next_index = 0

    @property
    def next_action(self) -> ReasoningAction | None:
        if self.next_index >= len(self.actions):
            return None
        return self.actions[self.next_index]


def prepare_action_batch(
    proposed_actions: Sequence[ReasoningAction],
    authorized_candidates: Sequence[BrowserAction],
    snapshot: SemanticSnapshot,
    *,
    run_id: str,
    page_id: str,
) -> PendingActionBatch | None:
    """Validate a small same-page sequence against this decision's candidates.

    Every proposed action must exactly match an authorized candidate. Only
    type, select, and check are allowed before the final action; click may
    appear only once, at the end. The returned queue is deliberately in-memory
    only because it contains user form values needed for execution.
    """
    if (
        not 2 <= len(proposed_actions) <= _BATCH_LIMIT
        or not run_id
        or not page_id
        or not authorized_candidates
    ):
        return None

    observation = _action_observation(snapshot)
    bound_actions: list[BrowserAction] = []
    try:
        bound_actions = [action.bind(observation) for action in proposed_actions]
    except ValueError:
        return None

    for bound in bound_actions:
        if not any(actions_match(bound, candidate) for candidate in authorized_candidates):
            return None

    action_types = {action.type for action in proposed_actions}
    form_family = bool(action_types <= _FORM_ACTIONS and action_types & _MUTATING_ACTIONS)
    tab_family = action_types == _TAB_ACTIONS
    if not (form_family or tab_family):
        return None
    if form_family and any(action.type == "click" for action in proposed_actions[:-1]):
        return None

    return PendingActionBatch(
        actions=tuple(proposed_actions),
        run_id=run_id,
        page_id=page_id,
        anchor=snapshot.model_copy(deep=True),
    )


def advance_action_batch(
    batch: PendingActionBatch,
    current: SemanticSnapshot,
    *,
    run_id: str,
    page_id: str,
    verification_success: bool,
    recovery_in_progress: bool,
    owned_tab_urls: Mapping[str, str] | None = None,
) -> ReasoningAction | None:
    """Return one next action only after the prior mutation is verified locally.

    Any run, page, generation, target identity, fingerprint, or unrelated state
    change clears the queue. ``same_decision_state`` already ignores focus, so
    focus movement caused by typing is tolerated.
    """
    previous = batch.previous_action
    if (
        not batch.actions
        or previous is None
        or run_id != batch.run_id
        or page_id != batch.page_id
        or not verification_success
        or recovery_in_progress
        or not _same_state_after_expected_mutation(
            batch.anchor,
            current,
            previous,
            owned_tab_urls=owned_tab_urls,
        )
    ):
        batch.clear()
        return None

    # Each verified action becomes the next local anchor. Only its expected
    # mutation is thereby carried forward; unrelated differences were rejected.
    batch.anchor = current.model_copy(deep=True)
    next_action = batch.next_action
    if next_action is None:
        batch.clear()
        return None
    batch.previous_action = next_action
    batch.next_index += 1
    return next_action


def mark_batch_action_started(batch: PendingActionBatch, action: ReasoningAction) -> bool:
    """Record the first dispatched action before the first verification step."""
    if not batch.actions or action != batch.actions[0] or batch.previous_action is not None:
        batch.clear()
        return False
    batch.previous_action = action
    return True


def _same_state_after_expected_mutation(
    anchor: SemanticSnapshot,
    current: SemanticSnapshot,
    action: ReasoningAction,
    *,
    owned_tab_urls: Mapping[str, str] | None = None,
) -> bool:
    if action.type == "new_tab":
        return _same_state_after_owned_tab_open(
            anchor,
            current,
            action,
            owned_tab_urls=owned_tab_urls,
        )
    if action.type not in _MUTATING_ACTIONS or action.target_ref is None:
        return False
    before_target = anchor.by_ref(action.target_ref)
    current_target = current.by_ref(action.target_ref)
    if before_target is None or current_target is None:
        return False
    if (
        anchor.page_fingerprint != current.page_fingerprint
        or anchor.tabs != current.tabs
        or anchor.active_frame != current.active_frame
    ):
        return False

    expected = before_target.model_copy(deep=True)
    if action.type == "type":
        if action.text is None:
            return False
        expected.value = action.text if action.clear else (expected.value or "") + action.text
    elif action.type == "select":
        if action.value is None:
            return False
        expected.value = action.value
    else:
        if action.checked is None:
            return False
        states = set(expected.state)
        states.discard("checked")
        states.discard("unchecked")
        if action.checked:
            states.add("checked")
        expected.state = sorted(states)

    current_states = sorted(state for state in current_target.state if state != "focused")
    expected_states = sorted(state for state in expected.state if state != "focused")
    if current_target.value != expected.value or current_states != expected_states:
        return False

    # Apply only the expected value/state to a copy of the anchor. Comparing it
    # with current keeps all other controls, fingerprints, geometry, and page
    # state strictly equal.
    expected_anchor = anchor.model_copy(deep=True)
    expected_anchor_target = expected_anchor.by_ref(action.target_ref)
    if expected_anchor_target is None:
        return False
    expected_anchor_target.value = expected.value
    expected_anchor_target.state = expected.state
    for collection_name in ("interactive_elements",):
        elements = getattr(expected_anchor, collection_name)
        interactive_target = next(
            (element for element in elements if element.ref == action.target_ref),
            None,
        )
        if interactive_target is not None:
            interactive_target.value = expected.value
            interactive_target.state = expected.state
    return same_decision_state(expected_anchor, current) and (
        _strict_snapshot_projection(expected_anchor) == _strict_snapshot_projection(current)
    )


def _same_state_after_owned_tab_open(
    anchor: SemanticSnapshot,
    current: SemanticSnapshot,
    action: ReasoningAction,
    *,
    owned_tab_urls: Mapping[str, str] | None,
) -> bool:
    if (
        action.url is None
        or owned_tab_urls is None
        or anchor.active_tab != current.active_tab
        or anchor.url != current.url
        or anchor.state_generation != current.state_generation
        or anchor.page_fingerprint != current.page_fingerprint
    ):
        return False

    before_tabs = set(anchor.tabs)
    after_tabs = set(current.tabs)
    added_tabs = after_tabs - before_tabs
    if len(added_tabs) != 1 or before_tabs - after_tabs:
        return False
    new_tab = next(iter(added_tabs))
    observed_url = owned_tab_urls.get(new_tab)
    expected_url = _normalize_tab_url(action.url)
    normalized_observed_url = _normalize_tab_url(observed_url or "")
    if not expected_url or normalized_observed_url != expected_url:
        return False

    # Tabs are allowed to differ only after the new owned tab and its URL have
    # been proven. No page state, control, geometry, or document field may move.
    expected_anchor = anchor.model_copy(deep=True)
    expected_anchor.tabs = list(current.tabs)
    return same_decision_state(expected_anchor, current) and (
        _strict_snapshot_projection(expected_anchor) == _strict_snapshot_projection(current)
    )


def _normalize_tab_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    host = parsed.hostname.casefold()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    default_port = 80 if parsed.scheme.casefold() == "http" else 443
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), netloc, path, parsed.query, parsed.fragment))


def _strict_snapshot_projection(snapshot: SemanticSnapshot) -> dict[str, object]:
    """Compare snapshot details omitted by the conservative state helper too."""
    projection = snapshot.model_dump(mode="python")
    projection.pop("focused", None)
    for collection in ("elements", "interactive_elements"):
        for element in projection[collection]:
            element["state"] = [state for state in element["state"] if state != "focused"]
    return projection


def _action_observation(snapshot: SemanticSnapshot) -> AgentObservation:
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
                state=element.state,
                interactable=element.interactable and element.visible and element.enabled,
            )
            for element in snapshot.elements
        ],
    )
