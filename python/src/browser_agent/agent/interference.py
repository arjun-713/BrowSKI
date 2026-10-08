"""Conservative state checks before dispatching a previously chosen action."""

from browser_agent._types import SemanticElement, SemanticSnapshot


def _element_state(element: SemanticElement) -> tuple[object, ...]:
    # Focus changes alone are expected while the panel requests approval.
    states = tuple(sorted(state for state in element.state if state != "focused"))
    rectangle = element.bbox
    geometry = (
        tuple(
            round(value) for value in (rectangle.x, rectangle.y, rectangle.width, rectangle.height)
        )
        if rectangle is not None
        else None
    )
    return (
        element.ref,
        element.fingerprint,
        element.role,
        element.accessible_name,
        element.text,
        element.value,
        states,
        element.visible,
        element.enabled,
        element.interactable,
        geometry,
    )


def same_decision_state(before: SemanticSnapshot, current: SemanticSnapshot) -> bool:
    """Reject changed documents, values, controls, and layout without logging data.

    A page fingerprint alone does not include every form value. This comparison
    is deliberately conservative; a changed state requires a fresh decision.
    It is a scheduling check, not a replacement for Rust's dispatch validation.
    """
    if (
        before.state_generation != current.state_generation
        or before.active_tab != current.active_tab
        or before.url != current.url
        or before.title != current.title
        or before.scroll != current.scroll
        or before.viewport != current.viewport
        or before.dialogs != current.dialogs
    ):
        return False
    previous = sorted(
        (_element_state(element) for element in before.elements), key=lambda row: str(row[0])
    )
    latest = sorted(
        (_element_state(element) for element in current.elements), key=lambda row: str(row[0])
    )
    return previous == latest
