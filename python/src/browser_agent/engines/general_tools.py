"""Conservative approval boundary around official Browser Use interaction tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from browser_agent.engines.browser_use_runtime import is_http_url
from browser_agent.engines.lifecycle import ActionApproval, ApprovalHandler

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
        target: [this.isConnected, this.disabled, this.readOnly, this.tagName,
                 this.type, rect.x, rect.y, rect.width, rect.height]
    });
    return state.length <= 1000000 ? state : null;
}"""


@dataclass
class InteractionPolicy:
    goal: str
    approve: ApprovalHandler | None = None
    blocked_reason: str | None = None


async def _target_state(
    browser: Any, index: int, *, text_input: bool
) -> tuple[object, str, str] | None:
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
    if text_input and (
        target[3] not in {"INPUT", "TEXTAREA"}
        or target[4] not in {"text", "search", "email", "tel", "url", "textarea"}
    ):
        return None
    # New input support is deliberately limited to ordinary main-document text
    # fields. Native dates, files, credentials and rich editors need separate proof.
    label = node.attributes.get("aria-label") or node.attributes.get("name") or node.tag_name
    identity = (node.backend_node_id, str(node.target_id), node.frame_id)
    return identity, hashlib.sha256(raw.encode()).hexdigest(), str(label)[:120]


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
            for operation in ("click", "input"):
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
                if operation == "input":
                    text = params.get("text")
                    if (
                        not isinstance(text, str)
                        or not 1 <= len(text) <= 4096
                        or params.get("clear", True) is not True
                        or not any(
                            f"{quote}{text}{quote}" in active_policy.goal for quote in ('"', "'")
                        )
                        or proposed.tag_name not in {"input", "textarea"}
                        or proposed.attributes.get("type", "text").lower()
                        not in {"text", "search", "email", "tel", "url"}
                    ):
                        return self.refuse(
                            "Text entry requires a quoted task literal and an ordinary text field."
                        )
                before = await _target_state(
                    browser_session, index, text_input=operation == "input"
                )
                identity = (proposed.backend_node_id, str(proposed.target_id), proposed.frame_id)
                if before is None or before[0] != identity:
                    return self.refuse("The proposed target changed; no action executed.")
                if active_policy.approve is None or not await active_policy.approve(
                    ActionApproval(action=operation, target=before[2])
                ):
                    return self.refuse(
                        "The pending action was denied, stopped or not approved in time."
                    )
                after = await _target_state(browser_session, index, text_input=operation == "input")
                if after is None or after[:2] != before[:2]:
                    return self.refuse(
                        "The page or target changed during approval; no action executed."
                    )
                result = await cast(Any, super()).act(action, browser_session, *args, **kwargs)
                if operation == "input" and not result.error:
                    page = await browser_session.get_current_page()
                    await browser_session.cdp_client.send.DOM.getDocument(
                        session_id=await page.session_id
                    )
                    element = await page.get_element(proposed.backend_node_id)
                    value = json.loads(await element.evaluate("() => JSON.stringify(this.value)"))
                    expected = params["text"]
                    if value != expected:
                        return self.refuse(
                            "Text entry did not produce the requested field value.", executed=True
                        )
                    result.metadata = {**(result.metadata or {}), "browski_verified": True}
                return result
            return await cast(Any, super()).act(action, browser_session, *args, **kwargs)

        def refuse(self, reason: str, *, executed: bool = False) -> ActionResult:
            active_policy.blocked_reason = reason
            return ActionResult(
                is_done=True,
                success=False,
                error=reason,
                metadata={"browski_executed": executed},
            )

    tools = ApprovedTools()
    allowed = {"navigate", "go_back", "wait", "scroll", "find_text", "done"}
    if active_policy.approve is not None:
        allowed.update({"click", "input"})
    for name in list(tools.registry.registry.actions):
        if name not in allowed:
            tools.registry.exclude_action(name)
    return tools
