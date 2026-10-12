"""Action matching ignores shared fields unrelated to the action type."""

from browser_agent._types import BrowserAction, ElementRef
from browser_agent.decisions.action_matching import actions_match


def _target() -> ElementRef:
    return ElementRef(ref="@save", id=41, generation=7)


def test_click_and_scroll_ignore_irrelevant_shared_defaults() -> None:
    click = BrowserAction(type="click", target=_target(), clear=True)
    proposed_click = BrowserAction(type="click", target=_target(), clear=False)
    scroll = BrowserAction(type="scroll", dx=0, dy=600, clear=True)
    proposed_scroll = BrowserAction(type="scroll", dx=0, dy=600, clear=False)

    assert actions_match(proposed_click, click)
    assert actions_match(proposed_scroll, scroll)


def test_matching_stays_strict_for_targets_generations_and_meaningful_fields() -> None:
    target = BrowserAction(type="click", target=_target())
    other_target = BrowserAction(
        type="click",
        target=ElementRef(ref="@cancel", id=42, generation=7),
    )
    stale_target = BrowserAction(
        type="click",
        target=ElementRef(ref="@save", id=41, generation=6),
    )
    typing = BrowserAction(
        type="type",
        target=_target(),
        text="Karnataka",
        clear=True,
        submit=False,
    )
    different_text = BrowserAction(
        type="type",
        target=_target(),
        text="Kerala",
        clear=True,
        submit=False,
    )
    different_clear = BrowserAction(
        type="type",
        target=_target(),
        text="Karnataka",
        clear=False,
        submit=False,
    )

    assert not actions_match(other_target, target)
    assert not actions_match(stale_target, target)
    assert not actions_match(different_text, typing)
    assert not actions_match(different_clear, typing)


def test_select_matches_value_and_selection_mode() -> None:
    authorized = BrowserAction(
        type="select",
        target=_target(),
        value="Karnataka",
        by="label",
    )

    assert actions_match(
        BrowserAction(
            type="select",
            target=_target(),
            value="Karnataka",
            by="label",
            clear=False,
        ),
        authorized,
    )
    assert not actions_match(
        BrowserAction(
            type="select",
            target=_target(),
            value="Karnataka",
            by="value",
        ),
        authorized,
    )


def test_action_type_must_match() -> None:
    assert not actions_match(
        BrowserAction(type="hover", target=_target()),
        BrowserAction(type="click", target=_target()),
    )


def test_verification_effect_and_options_remain_authorized_fields() -> None:
    authorized = BrowserAction(type="click", target=_target())
    altered_effect = BrowserAction(
        type="click",
        target=_target(),
        expected_effect={"url_contains": "account"},
    )
    altered_options = BrowserAction(
        type="click",
        target=_target(),
        options={"force": True},
    )

    assert not actions_match(altered_effect, authorized)
    assert not actions_match(altered_options, authorized)
