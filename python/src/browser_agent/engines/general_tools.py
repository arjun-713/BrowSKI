"""Conservative approval boundary around official Browser Use interaction tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from browser_agent.engines.browser_use_runtime import is_http_url
from browser_agent.engines.lifecycle import ActionApproval, ApprovalHandler
from browser_agent.engines.native_fields import (
    native_field_state,
    post_native_field_state,
    resolve_native_option,
    validate_native_date,
)
from browser_agent.task_literals import TaskLiteralError, normalize_field_label

if TYPE_CHECKING:
    from browser_use import Tools


# Fixed browser-owned inspection, never model-authored JavaScript. The raw state
# stays in memory; only its hash survives the approval wait. Refuse huge pages
# instead of treating a truncated page as an unchanged page.
_APPROVAL_STATE = """() => {
    const doc = this.ownerDocument;
    if (doc.defaultView !== doc.defaultView.top) return null;
    const html = doc.documentElement.outerHTML;
    if (html.length > 1000000) return null;
    const rect = this.getBoundingClientRect();
    const state = JSON.stringify({
        url: doc.location.href, documentEpoch: doc.defaultView.performance.timeOrigin, html,
        values: Array.from(doc.querySelectorAll('input,textarea,select')).map(e =>
            [e.type === 'password' ? null : e.value, e.checked, e.selectedIndex]),
        target: [this.isConnected, this.matches(':disabled'), this.readOnly, this.tagName,
                 this.type, rect.x, rect.y, rect.width, rect.height]
    });
    return state.length <= 1000000 ? state : null;
}"""


@dataclass
class InteractionPolicy:
    goal: str
    approve: ApprovalHandler | None = None
    blocked_reason: str | None = None
    blocked_phase: str = "approval"
    native_fields: bool = False
    values_by_label: dict[str, str] | None = None


@dataclass(frozen=True)
class _ApprovalTarget:
    identity: tuple[int, str, str | None]
    fingerprint: str
    label: str
    url: str
    epoch: float


async def _target_state(
    browser: Any, index: int, *, text_input: bool, native_fields: bool = False
) -> _ApprovalTarget | None:
    """Refresh the upstream selector map and bind approval to the exact live node/page."""
    await browser.get_browser_state_summary(include_screenshot=False, cached=False)
    node = await browser.get_element_by_index(index)
    page = await browser.get_current_page()
    if node is None or page is None:
        return None
    # The pinned actor resolves backend IDs through frontend node IDs. Chromium
    # requires this document request first; keep transport ownership upstream.
    await browser.cdp_client.send.DOM.getDocument(session_id=await page.session_id)
    element = await page.get_element(node.backend_node_id)
    raw = await element.evaluate(_APPROVAL_STATE)
    if not raw or raw == "null":
        return None
    data = json.loads(raw)
    target = data["target"]
    if not target[0] or target[1] or target[2] or target[7] <= 0 or target[8] <= 0:
        return None
    input_types = {"text", "search", "email", "tel", "url", "textarea"}
    if native_fields:
        input_types.add("date")
    if text_input and (target[3] not in {"INPUT", "TEXTAREA"} or target[4] not in input_types):
        return None
    # General permits ordinary main-document text fields; Fast explicitly opts
    # into native dates. Files, credentials and rich editors remain excluded.
    label = (
        (node.ax_node.name if node.ax_node is not None else None)
        or node.attributes.get("aria-label")
        or node.attributes.get("name")
        or node.tag_name
    )
    identity = (node.backend_node_id, str(node.target_id), node.frame_id)
    return _ApprovalTarget(
        identity,
        hashlib.sha256(raw.encode()).hexdigest(),
        str(label)[:120],
        data["url"],
        data["documentEpoch"],
    )


def navigation_tools(policy: InteractionPolicy | None = None) -> Tools[Any]:
    """Use the official executor; no arbitrary code, keyboard, file or coordinate actions."""
    from browser_use import Tools
    from browser_use.agent.views import ActionResult

    active_policy = policy or InteractionPolicy(goal="")

    class ApprovedTools(Tools[Any]):
        async def act(self, action: Any, browser_session: Any, *args: Any, **kwargs: Any) -> Any:
            payload = action.model_dump(exclude_unset=True, exclude_none=True)
            if len(payload) != 1:
                return self.refuse("Exactly one action may be proposed at a time.")
            navigate = cast(dict[str, object] | None, payload.get("navigate"))
            if isinstance(navigate, dict) and not is_http_url(navigate.get("url")):
                return ActionResult(
                    error="Only HTTP(S) navigation without credentials is permitted."
                )
            for operation in ("click", "input", "select_dropdown"):
                if operation not in payload:
                    continue
                raw_params = payload[operation]
                if not isinstance(raw_params, dict):
                    return self.refuse("A fresh indexed target is required.")
                params = cast(dict[str, Any], raw_params)
                if type(params.get("index")) is not int:
                    return self.refuse("A fresh indexed target is required.")
                index = params["index"]
                # Capture the proposed identity before refreshing indexes. A new
                # snapshot may assign an old index to a different element.
                proposed = await browser_session.get_element_by_index(index)
                if proposed is None:
                    return self.refuse("The proposed target is unavailable; no action executed.")
                expected: str | None = None
                desired_option: str | None = None
                native_kind = ""
                if operation == "input":
                    text = params.get("text")
                    if (
                        not isinstance(text, str)
                        or not 1 <= len(text) <= 4096
                        or any(
                            ord(character) < 0x20 or ord(character) == 0x7F for character in text
                        )
                        or params.get("clear", True) is not True
                        or not any(
                            f"{quote}{text}{quote}" in active_policy.goal for quote in ('"', "'")
                        )
                        or proposed.tag_name not in {"input", "textarea"}
                        or proposed.attributes.get("type", "text").lower()
                        not in (
                            {"text", "search", "email", "tel", "url"}
                            | ({"date"} if active_policy.native_fields else set())
                        )
                    ):
                        return self.refuse(
                            "Text entry requires a quoted task literal and an ordinary text field."
                        )
                    expected = text
                elif operation == "select_dropdown":
                    if not active_policy.native_fields or proposed.tag_name != "select":
                        return self.refuse(
                            "Only explicitly enabled native selections are supported."
                        )
                before = await _target_state(
                    browser_session,
                    index,
                    text_input=operation == "input",
                    native_fields=active_policy.native_fields,
                )
                identity = (proposed.backend_node_id, str(proposed.target_id), proposed.frame_id)
                if before is None or before.identity != identity:
                    return self.refuse("The proposed target changed; no action executed.")
                if operation in {"input", "select_dropdown"}:
                    key = normalize_field_label(before.label)
                    bound = (active_policy.values_by_label or {}).get(key)
                    if active_policy.values_by_label is not None and (
                        bound is None or (operation == "input" and bound != expected)
                    ):
                        return self.refuse(
                            "The proposed input does not match this field's task value."
                        )
                    native = await native_field_state(browser_session, proposed, expected)
                    if native is None:
                        return self.refuse(
                            "Native field state is unavailable or exceeds its bounds."
                        )
                    if native.disabled or native.read_only:
                        return self.refuse("The native field is disabled or read-only.")
                    native_kind = native.kind
                    if operation == "input":
                        if native.kind == "date":
                            try:
                                validate_native_date(str(expected))
                            except TaskLiteralError as error:
                                return self.refuse(str(error))
                        if native.proposed_valid is not True:
                            return self.refuse(
                                "The requested value violates native field constraints."
                            )
                    else:
                        desired_option = bound
                        choice = resolve_native_option(native, bound) if bound is not None else None
                        if choice is None or params.get("text") != choice[0]:
                            return self.refuse(
                                "The requested native option is missing or ambiguous."
                            )
                        expected = choice[1].value
                if active_policy.approve is None or not await active_policy.approve(
                    ActionApproval(
                        action="select option" if operation == "select_dropdown" else operation,
                        target=before.label,
                    )
                ):
                    return self.refuse(
                        "The pending action was denied, stopped or not approved in time."
                    )
                after = await _target_state(
                    browser_session,
                    index,
                    text_input=operation == "input",
                    native_fields=active_policy.native_fields,
                )
                if after is None or (
                    after.identity != before.identity or after.fingerprint != before.fingerprint
                ):
                    return self.refuse(
                        "The page or target changed during approval; no action executed."
                    )
                result = await cast(Any, super()).act(action, browser_session, *args, **kwargs)
                if expected is not None and not result.error:
                    native, reacquired = await post_native_field_state(
                        browser_session,
                        proposed,
                        label=before.label,
                        url=before.url,
                        epoch=before.epoch,
                        kind=native_kind,
                    )
                    choice = (
                        resolve_native_option(native, desired_option)
                        if native is not None and desired_option is not None
                        else None
                    )
                    if (
                        native is None
                        or native.value != expected
                        or not native.valid
                        or (
                            desired_option is not None
                            and (choice is None or not choice[1].selected)
                        )
                    ):
                        return self.refuse(
                            "The requested field value or selected option was not verified.",
                            executed=True,
                            reacquired=reacquired,
                        )
                    result.metadata = {
                        **(result.metadata or {}),
                        "browski_verified": True,
                        "browski_reacquired": reacquired,
                    }
                return result
            return await cast(Any, super()).act(action, browser_session, *args, **kwargs)

        def refuse(
            self, reason: str, *, executed: bool = False, reacquired: bool = False
        ) -> ActionResult:
            active_policy.blocked_reason = reason
            active_policy.blocked_phase = "verification" if executed else "approval"
            return ActionResult(
                is_done=True,
                success=False,
                error=reason,
                metadata={"browski_executed": executed, "browski_reacquired": reacquired},
            )

    tools = ApprovedTools()
    allowed = {"navigate", "go_back", "wait", "scroll", "find_text", "done"}
    if active_policy.approve is not None:
        allowed.update({"click", "input"})
        if active_policy.native_fields:
            allowed.add("select_dropdown")
    for name in list(tools.registry.registry.actions):
        if name not in allowed:
            tools.registry.exclude_action(name)
    return tools
