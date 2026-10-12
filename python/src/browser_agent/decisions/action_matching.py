"""Compare browser actions by the fields that define each action's intent."""

from __future__ import annotations

from typing import Any

from browser_agent._types import BrowserAction

_FIELDS_BY_ACTION: dict[str, tuple[str, ...]] = {
    "click": ("target",),
    "type": ("target", "text", "clear", "submit"),
    "select": ("target", "value", "by"),
    "check": ("target", "checked"),
    "press": ("target", "key"),
    "scroll": ("dx", "dy"),
    "hover": ("target",),
    "navigate": ("url",),
    "back": (),
    "forward": (),
    "reload": (),
    "activate_tab": ("tab",),
    "close_tab": ("tab",),
    "new_tab": ("url",),
    "handle_dialog": ("accept",),
    "wait": ("ms",),
}
_AUTHORIZATION_FIELDS = ("expected_effect", "options")


def actions_match(proposed: BrowserAction, authorized: BrowserAction) -> bool:
    """Return whether ``proposed`` preserves an authorized action's intent.

    BrowserAction has shared default fields, such as ``clear`` and ``checked``.
    Those defaults do not constrain action types that do not use them. Every
    parameter that changes the meaning of the proposed action is compared,
    including the semantic target reference and generation.
    """
    if proposed.type != authorized.type:
        return False

    fields = _FIELDS_BY_ACTION.get(proposed.type)
    if fields is None:
        return False

    fields_to_match = (*fields, *_AUTHORIZATION_FIELDS)
    return all(
        _field_value(proposed, field) == _field_value(authorized, field)
        for field in fields_to_match
    )


def _field_value(action: BrowserAction, field: str) -> Any:
    value = getattr(action, field)
    if field != "target" or value is None:
        return value
    return value.ref, value.generation
