"""Bounded native control inspection through the task's existing Browser Use session."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from browser_agent.task_literals import TaskLiteralError, normalize_field_label


@dataclass(frozen=True)
class ActionExecution:
    invoked: bool
    # An approved click awaits independent outcome evidence in the task loop.
    verified: bool | None
    reacquired: bool = False


async def native_action_state(browser: Any, node: Any) -> str | None:
    """Bind a named click to its live native action and form destination."""
    page = await browser.get_current_page()
    if page is None:
        return None
    await browser.cdp_client.send.DOM.getDocument(session_id=await page.session_id)
    element = await page.get_element(node.backend_node_id)
    raw = await element.evaluate("""() => {
        if (!this.isConnected || this.ownerDocument.defaultView !==
            this.ownerDocument.defaultView.top || this.matches(':disabled') ||
            this.getAttribute('aria-disabled') === 'true') return null;
        const rect = this.getBoundingClientRect();
        if (!rect.width || !rect.height) return null;
        const form = this.form;
        let formAction = form ? form.action : null;
        if (form && this.hasAttribute('formaction')) formAction = this.formAction;
        const state = JSON.stringify({
            tag: this.tagName, type: this.type, href: this.href ?? null,
            formAction,
            formMethod: form ? (this.getAttribute('formmethod') || form.method) : null,
            formTarget: form ? (this.getAttribute('formtarget') || form.target) : null
        });
        return state.length <= 8192 ? state : null;
    }""")
    return None if not raw or raw == "null" else raw


class NativeOption(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    label: str = Field(max_length=500)
    sdk_text: str = Field(max_length=500)
    value: str = Field(max_length=2048)
    disabled: bool
    selected: bool


class NativeFieldState(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    kind: str
    value: str = Field(max_length=65536)
    valid: bool
    disabled: bool
    read_only: bool
    multiple: bool
    proposed_valid: bool | None
    options: tuple[NativeOption, ...] = Field(max_length=1000)


async def native_field_state(
    browser: Any, node: Any, proposed: str | None = None
) -> NativeFieldState | None:
    """Read actual properties; a detached clone checks native constraints without events."""
    page = await browser.get_current_page()
    if page is None:
        return None
    await browser.cdp_client.send.DOM.getDocument(session_id=await page.session_id)
    element = await page.get_element(node.backend_node_id)
    raw = await element.evaluate(
        """(proposed) => {
            if (!this.isConnected ||
                this.ownerDocument.defaultView !== this.ownerDocument.defaultView.top ||
                !['INPUT','TEXTAREA','SELECT'].includes(this.tagName)) return null;
            if (!['text','search','email','tel','url','textarea','date',
                  'select-one','select-multiple'].includes(this.type)) return null;
            if (this.options && this.options.length > 1000) return null;
            let proposedValid = null;
            if (proposed !== null) {
                const clone = this.cloneNode(true);
                clone.value = proposed;
                proposedValid = clone.value === proposed && clone.validity.valid;
            }
            const state = JSON.stringify({
                kind: this.type, value: this.value, valid: this.validity.valid,
                disabled: this.matches(':disabled'), read_only: Boolean(this.readOnly),
                multiple: Boolean(this.multiple), proposed_valid: proposedValid,
                options: this.tagName === 'SELECT' ? Array.from(this.options).map(o => ({
                    label: o.label.trim(), sdk_text: o.text.trim(),
                    value: o.value, selected: o.selected,
                    disabled: o.disabled || (o.parentElement.tagName === 'OPTGROUP' &&
                                             o.parentElement.disabled)
                })) : []
            });
            return state.length <= 1000000 ? state : null;
        }""",
        proposed,
    )
    return None if not raw or raw == "null" else NativeFieldState.model_validate_json(raw)


def validate_native_date(value: str) -> None:
    try:
        if date.fromisoformat(value).isoformat() == value:
            return
    except ValueError:
        pass
    raise TaskLiteralError("Native dates require a valid YYYY-MM-DD task literal.")


def resolve_native_option(state: NativeFieldState, desired: str) -> tuple[str, NativeOption] | None:
    """Prefer one visible label, else one value; require an unambiguous SDK token."""
    if state.kind != "select-one" or state.multiple:
        return None
    normalized = normalize_field_label(desired)
    labels = [
        option for option in state.options if normalize_field_label(option.label) == normalized
    ]
    matches = labels or [
        option for option in state.options if normalize_field_label(option.value) == normalized
    ]
    if len(matches) != 1 or matches[0].disabled:
        return None
    option = matches[0]
    # Upstream matches exact lower-case label OR value, taking the first. A
    # unique visible label may still collide with another option's value; use
    # its canonical value only when that token identifies this same option.
    for token in (option.sdk_text, option.value):
        if not token:
            continue
        native_matches = [
            item
            for item in state.options
            if token.lower() in {item.sdk_text.lower(), item.value.lower()}
        ]
        if len(native_matches) == 1 and native_matches[0] == option:
            return token, option
    return None


async def post_native_field_state(
    browser: Any, node: Any, *, label: str, url: str, epoch: float, kind: str
) -> tuple[NativeFieldState | None, bool]:
    """One semantic reread after replacement; never repeat the user's write."""
    failure: RuntimeError | None = None
    try:
        state = await native_field_state(browser, node)
        if state is not None:
            return (state if state.kind == kind else None), False
    except RuntimeError as error:
        failure = error
    fresh = await browser.get_browser_state_summary(include_screenshot=False, cached=False)
    page = await browser.get_current_page()
    if page is None:
        return None, False
    current = json.loads(
        await page.evaluate(
            "() => JSON.stringify({url: location.href, epoch: performance.timeOrigin})"
        )
    )
    if current["url"] != url or current["epoch"] != epoch:
        return None, False
    nodes = list(fresh.dom_state.selector_map.values())
    if any(
        n.backend_node_id == node.backend_node_id and n.target_id == node.target_id for n in nodes
    ):
        if failure is not None:
            raise failure
        return None, False
    matches = [
        candidate
        for candidate in nodes
        if candidate.target_id == node.target_id
        and candidate.frame_id == node.frame_id
        and candidate.tag_name == node.tag_name
        and normalize_field_label(
            (candidate.ax_node.name if candidate.ax_node is not None else None)
            or candidate.attributes.get("aria-label")
            or candidate.attributes.get("name", "")
        )
        == normalize_field_label(label)
    ]
    if len(matches) != 1:
        return None, False
    state = await native_field_state(browser, matches[0])
    if state is None or state.kind != kind:
        return None, False
    return state, True
