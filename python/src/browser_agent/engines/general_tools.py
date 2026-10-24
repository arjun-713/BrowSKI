"""Conservative approval boundary around official Browser Use interaction tools."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from browser_agent.engines.browser_use_runtime import is_http_url, read_page_evidence
from browser_agent.engines.lifecycle import ActionApproval, ApprovalHandler
from browser_agent.engines.native_fields import (
    native_field_state,
    post_native_field_state,
    resolve_native_option,
    validate_native_date,
)
from browser_agent.engines.owned_tabs import OwnedTab, TabStateChanged, focus_owned_tab
from browser_agent.engines.risk import RISK_TARGET_SCRIPT, RiskTarget, classify_risk
from browser_agent.engines.source_transfer import SourceTransfer
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
            [e.value, e.checked, e.selectedIndex]),
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
    source: SourceTransfer | None = None
    model_authored: bool = False
    public_goal: str = ""
    notify: Callable[[str, str, str, str | None, bool | None], Awaitable[None]] | None = None
    secrets: set[str] = field(default_factory=set[str])
    search_engine: str = "google"
    last_action: str | None = None
    identical_actions: int = 0

    def repeats_without_progress(self, signature: str) -> bool:
        """Stagnation guard: the same action on the same unchanged page (principle 9)."""
        if signature == self.last_action:
            self.identical_actions += 1
        else:
            self.last_action, self.identical_actions = signature, 1
        return self.identical_actions > MAX_IDENTICAL_ACTIONS

    def redact(self, text: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            if secret:
                from urllib.parse import quote, quote_plus

                for encoded in {secret, quote(secret, safe=""), quote_plus(secret, safe="")}:
                    text = text.replace(encoded, "••••")
        return text

    async def event(
        self, kind: str, operation: str, label: str, url: str | None, verified: bool | None = None
    ) -> None:
        if self.notify is not None:
            await self.notify(
                kind,
                operation,
                self.redact(label)[:160],
                self.redact(url) if url else None,
                verified,
            )


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


# Cheap, in-page progress fingerprint for the stagnation guard. Hashing happens
# in the page, so a few bytes cross the relay instead of the whole document.
_PAGE_FINGERPRINT = """() => {
    const doc = this.ownerDocument;
    const values = Array.from(doc.querySelectorAll('input,textarea,select'), e =>
        e.type === 'password' ? '' : `${e.value}|${e.checked}|${e.selectedIndex}`).join(',');
    const text = [doc.location.href, doc.body ? doc.body.innerText : '', values,
                  this.outerHTML, this.isConnected].join('\\u0001');
    let hash = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193);
    }
    return `${text.length}:${(hash >>> 0).toString(16)}`;
}"""

# A second identical try is allowed (some controls need it); a third is refused.
MAX_IDENTICAL_ACTIONS = 2

_SEARCH_ENGINE_NAMES = {"google": "Google", "bing": "Bing", "duckduckgo": "DuckDuckGo"}
_MAX_LABEL_CHARS = 160  # EngineEvent.label bound, shared with the panel protocol.


def _bounded_label(text: str) -> str:
    if len(text) <= _MAX_LABEL_CHARS:
        return text
    return text[: _MAX_LABEL_CHARS - 1].rstrip() + "…"


def search_engine_for(policy: InteractionPolicy) -> str:
    """The engine the user named in the task, otherwise the configured one."""
    named = [
        engine
        for engine in ("google", "bing", "duckduckgo")
        if re.search(rf"\b{engine}\b", policy.goal, re.IGNORECASE)
    ]
    return named[0] if len(named) == 1 else policy.search_engine


def navigation_tools(policy: InteractionPolicy | None = None) -> Tools[Any]:
    """Use the official executor; no arbitrary code, keyboard, file or coordinate actions."""
    from browser_use import Tools
    from browser_use.agent.views import ActionResult

    active_policy = policy or InteractionPolicy(goal="")

    class ApprovedTools(Tools[Any]):
        async def act(self, action: Any, browser_session: Any, *args: Any, **kwargs: Any) -> Any:
            if active_policy.model_authored:
                return await self.act_general(action, browser_session, *args, **kwargs)
            payload = action.model_dump(exclude_unset=True, exclude_none=True)
            if len(payload) != 1:
                return self.refuse("Exactly one action may be proposed at a time.")
            navigate = cast(dict[str, object] | None, payload.get("navigate"))
            if isinstance(navigate, dict) and not is_http_url(navigate.get("url")):
                return ActionResult(
                    error="Only HTTP(S) navigation without credentials is permitted."
                )
            if "switch" in payload:
                return await self.switch_owned(payload, browser_session)
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
                        or not (
                            any(
                                f"{quote}{text}{quote}" in active_policy.goal
                                for quote in ('"', "'")
                            )
                            or (
                                active_policy.source is not None
                                and active_policy.source.matches_input(
                                    proposed.ax_node.name if proposed.ax_node else "",
                                    text,
                                    str(proposed.target_id),
                                )
                            )
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
                source_required = active_policy.source is not None and (
                    operation == "click"
                    or normalize_field_label(before.label) == active_policy.source.destination_label
                )
                if source_required and active_policy.source is not None:
                    if not await active_policy.source.verify(browser_session):
                        return self.refuse("The supporting source is no longer verified.")
                if active_policy.approve is None or not await active_policy.approve(
                    ActionApproval(
                        action="select option" if operation == "select_dropdown" else operation,
                        target=before.label,
                    )
                ):
                    return self.refuse(
                        "The pending action was denied, stopped or not approved in time."
                    )
                if source_required and active_policy.source is not None:
                    if not await active_policy.source.verify(browser_session):
                        return self.refuse("The supporting source changed during approval.")
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
                    if source_required and active_policy.source is not None:
                        if not await active_policy.source.verify(browser_session):
                            return self.refuse(
                                "The supporting source changed during input; "
                                "its result is unverified.",
                                executed=True,
                            )
                return result
            return await cast(Any, super()).act(action, browser_session, *args, **kwargs)

        async def switch_owned(self, payload: dict[str, Any], browser_session: Any) -> Any:
            switch = cast(dict[str, object] | None, payload.get("switch"))
            if isinstance(switch, dict):
                tab_id = switch.get("tab_id")
                matches = [
                    target
                    for target in browser_session.get_page_targets()
                    if isinstance(tab_id, str)
                    and 1 <= len(tab_id) <= 100
                    and str(target.target_id).endswith(tab_id)
                ]
                if len(matches) != 1:
                    return ActionResult(
                        error="The owned tab target is unavailable or ambiguous.",
                        metadata={"browski_executed": False},
                    )
                from browser_use.actor.page import Page

                target_id = str(matches[0].target_id)
                evidence = await read_page_evidence(Page(browser_session, target_id))
                if not is_http_url(evidence.url):
                    return ActionResult(
                        error="Only owned HTTP(S) task tabs may be selected.",
                        metadata={"browski_executed": False},
                    )
                try:
                    await focus_owned_tab(browser_session, OwnedTab(target_id, evidence))
                except TabStateChanged as changed:
                    return ActionResult(
                        error="The owned tab focus was not verified.",
                        metadata={"browski_executed": changed.invoked},
                    )
                return ActionResult(
                    extracted_content=f"Selected owned tab {target_id[-4:]}.",
                    metadata={"browski_executed": True, "browski_verified": True},
                )

        async def act_general(self, action: Any, browser: Any, *args: Any, **kwargs: Any) -> Any:
            """Rebind every mutation; reserve approval for consequential actions."""
            payload = action.model_dump(exclude_unset=True, exclude_none=True)
            if len(payload) != 1:
                return self.refuse("Exactly one action may be proposed at a time.")
            operation, params = next(iter(payload.items()))
            if operation == "search":
                # Upstream prefers DuckDuckGo to dodge captchas in throwaway
                # browsers; in the user's own profile the configured engine fits.
                params = {**params, "engine": search_engine_for(active_policy)}
                action = cast(Any, type(action)).model_validate({"search": params})
            if operation in {"evaluate", "upload_file"}:
                return self.refuse("This action is unavailable under the browser policy.")
            if operation == "navigate" and not is_http_url(params.get("url")):
                return self.refuse("Only HTTP(S) navigation without credentials is permitted.")
            target: RiskTarget | None = None
            before: _ApprovalTarget | None = None
            index = params.get("index")
            if operation in {"click", "input", "select_dropdown", "send_keys"}:
                if operation == "send_keys":
                    index = await self.focused_index(browser)
                if type(index) is not int:
                    return self.refuse(
                        "A fresh indexed target is required; observe the page again.",
                        phase="freshness",
                    )
                # Classify on the element the agent observed. The expensive fresh
                # capture and page binding are reserved for risky actions below.
                proposed = await browser.get_element_by_index(index)
                page = await browser.get_current_page()
                if proposed is None or page is None:
                    return self.refuse(
                        "The proposed target changed; observe the page again.", phase="freshness"
                    )
                identity = (proposed.backend_node_id, str(proposed.target_id), proposed.frame_id)
                await browser.cdp_client.send.DOM.getDocument(session_id=await page.session_id)
                try:
                    element = await page.get_element(proposed.backend_node_id)
                    target = RiskTarget.model_validate_json(
                        await element.evaluate(RISK_TARGET_SCRIPT)
                    )
                    fingerprint = str(await element.evaluate(_PAGE_FINGERPRINT))
                except Exception:
                    return self.refuse(
                        "The proposed target changed; observe the page again.", phase="freshness"
                    )
                if (target.href and not is_http_url(target.href)) or (
                    target.form_action
                    and not is_http_url(target.form_action)
                    and (operation == "send_keys" or target.input_type == "submit")
                ):
                    return self.refuse("Only HTTP(S) navigation without credentials is permitted.")
                # The fingerprint covers the URL, page text, form values and target,
                # so an identical signature means nothing changed since the last try.
                signature = json.dumps([operation, identity, fingerprint, params.get("text")])
                if active_policy.repeats_without_progress(signature):
                    return self.refuse(
                        f"“{target.label}” was already tried {MAX_IDENTICAL_ACTIONS} times "
                        "without changing the page. Choose a different element (for example "
                        "the option itself rather than its heading), scroll, or read the page.",
                        phase="stagnation",
                    )
                if operation == "send_keys" and target.sensitive:
                    keys = str(params.get("keys", ""))
                    safe_keys = {
                        "Enter",
                        "Return",
                        "Tab",
                        "Shift+Tab",
                        "Backspace",
                        "Delete",
                        "Control+a",
                        "Control+A",
                        "Ctrl+A",
                    }
                    if keys not in safe_keys:
                        active_policy.secrets.add(keys)
                        return self.refuse("Use the input action for sensitive text entry.")
                if operation == "input" and target.sensitive:
                    text = params.get("text", "")
                    active_policy.secrets.add(text)
                    # Upstream marks substituted secrets sensitive and omits their
                    # values from action results and typing logs.
                    safe_payload = {
                        "input": {**params, "text": "<secret>browski_sensitive</secret>"}
                    }
                    action = cast(Any, type(action)).model_validate(safe_payload)
                    kwargs["sensitive_data"] = {"browski_sensitive": text}
                risk = classify_risk(operation, target, keys=params.get("keys", ""))
                if risk is not None:
                    # Bind the approval to the exact live node and page state.
                    before = await _target_state(browser, index, text_input=False)
                    if before is None or before.identity != identity:
                        return self.refuse(
                            "The proposed target changed; observe the page again.",
                            phase="freshness",
                        )
                    reason = risk[1]
                    if active_policy.approve is None:
                        return self.refuse(
                            f"Approval is required: {reason}; choose another approach or finish."
                        )
                    approved = await active_policy.approve(
                        ActionApproval(action=operation, target=target.label, reason=reason)
                    )
                    if not approved:
                        return self.refuse(
                            f"The user declined: {reason}; choose another approach or finish"
                        )
                    after = await _target_state(browser, index, text_input=False)
                    if (
                        after is None
                        or after.identity != before.identity
                        or after.fingerprint != before.fingerprint
                    ):
                        return self.refuse(
                            "The page or target changed during approval; observe the page again.",
                            phase="freshness",
                        )
                    if operation == "send_keys" and await self.focused_index(browser) != index:
                        return self.refuse(
                            "The focused field changed during approval; observe the page again.",
                            phase="freshness",
                        )
            page = await browser.get_current_page()
            url = (
                target.page_url
                if target is not None
                else str(params["url"])
                if operation == "navigate"
                else (await read_page_evidence(page)).url
                if page
                else None
            )
            label = self.action_label(operation, params, target)
            if operation == "switch":
                matches = [
                    t
                    for t in browser.get_page_targets()
                    if str(t.target_id).endswith(str(params.get("tab_id", "")))
                ]
                if len(matches) == 1:
                    label = _bounded_label(f"Switched to tab “{matches[0].title}”")
            await active_policy.event("action_started", operation, label, url)
            result: Any
            if operation == "switch":
                result = await self.switch_owned(payload, browser)
            elif operation == "navigate":
                result = await self.navigate_fast(params, browser)
            else:
                result = await cast(Any, super()).act(action, browser, *args, **kwargs)
            active_policy.blocked_reason = None
            # An executor return is an action result, not independent outcome
            # proof. Only the owned-tab verifier can set verified here.
            metadata = cast(dict[str, object], result.metadata or {})
            verified = metadata.get("browski_verified")
            await active_policy.event(
                "browser_failed" if result.error else "action_finished",
                operation,
                label,
                url,
                False if result.error else True if verified is True else None,
            )
            return result

        async def navigate_fast(self, params: dict[str, Any], browser: Any) -> ActionResult:
            """Navigate once the document is parsed rather than fully loaded.

            Upstream waits for the load event (every image, ad and tracker) and then
            captures the page a second time for a blank-page check; the agent's next
            step observes the page anyway. Measured on store pages this saved
            seconds per navigation. The HTTP(S) policy check has already run.
            """
            from browser_use.browser.events import NavigateToUrlEvent

            url = str(params["url"])
            new_tab = bool(params.get("new_tab"))
            try:
                event = browser.event_bus.dispatch(
                    NavigateToUrlEvent(url=url, new_tab=new_tab, wait_until="domcontentloaded")
                )
                await event
                await event.event_result(raise_if_any=True, raise_if_none=False)
            except Exception as error:
                return ActionResult(
                    error=f"Navigation to {url} failed ({type(error).__name__}); try another page."
                )
            memory = f"Opened new tab with URL {url}" if new_tab else f"Navigated to {url}"
            return ActionResult(extracted_content=memory, long_term_memory=memory)

        async def focused_index(self, browser: Any, *, refresh: bool = False) -> int | None:
            """Index of the focused field; refreshes the page map only when it is missing."""
            if refresh:
                await browser.get_browser_state_summary(include_screenshot=False, cached=False)
            page = await browser.get_current_page()
            if page is None:
                return None
            # Resolve the actual focused node, not a previously focused selector.
            session_id = await page.session_id
            result = await browser.cdp_client.send.Runtime.evaluate(
                params={"expression": "document.activeElement", "returnByValue": False},
                session_id=session_id,
            )
            object_id = result.get("result", {}).get("objectId")
            if not object_id:
                return None
            try:
                described = await browser.cdp_client.send.DOM.describeNode(
                    params={"objectId": object_id}, session_id=session_id
                )
                backend_id = described["node"]["backendNodeId"]
            finally:
                await browser.cdp_client.send.Runtime.releaseObject(
                    params={"objectId": object_id}, session_id=session_id
                )
            selectors = await browser.get_selector_map()
            found = next(
                (i for i, node in selectors.items() if node.backend_node_id == backend_id), None
            )
            if found is None and not refresh:
                return await self.focused_index(browser, refresh=True)
            return found

        def action_label(
            self, operation: str, params: dict[str, Any], target: RiskTarget | None
        ) -> str:
            from urllib.parse import urlsplit

            name = target.label if target is not None else "field"
            if operation == "input":
                text = (
                    "••••"
                    if target is not None and target.sensitive
                    else str(params.get("text", ""))[:80]
                )
                return _bounded_label(f"Typed “{text}” into {name}")
            if operation == "click":
                return _bounded_label(f"Clicked “{name}”")
            if operation == "navigate":
                return f"Opened {urlsplit(str(params['url'])).hostname}"
            if operation == "search":
                engine = _SEARCH_ENGINE_NAMES.get(str(params.get("engine")), "the web")
                return _bounded_label(f"Searched {engine} for “{str(params.get('query', ''))}”")
            if operation == "send_keys":
                return f"Pressed {params.get('keys', '')[:60]}"
            if operation == "select_dropdown":
                return _bounded_label(f"Selected an option in {name}")
            if operation == "scroll":
                return "Scrolled down" if params.get("down", True) else "Scrolled up"
            if operation == "switch":
                return f"Switched to tab {params.get('tab_id', '')}"
            return {
                "extract": "Read the page",
                "done": "Prepared the answer",
                "wait": "Waited",
                "go_back": "Went back",
            }.get(operation, "Read the page")

        def refuse(
            self,
            reason: str,
            *,
            executed: bool = False,
            reacquired: bool = False,
            phase: str | None = None,
        ) -> ActionResult:
            active_policy.blocked_reason = reason
            active_policy.blocked_phase = phase or ("verification" if executed else "approval")
            return ActionResult(
                is_done=not active_policy.model_authored,
                success=False if not active_policy.model_authored else None,
                error=reason,
                metadata={"browski_executed": executed, "browski_reacquired": reacquired},
            )

    tools = ApprovedTools()
    if active_policy.model_authored:
        tools.registry.exclude_action("evaluate")
        tools.registry.exclude_action("upload_file")
        return tools
    allowed = {"navigate", "go_back", "wait", "scroll", "find_text", "switch", "done"}
    if active_policy.approve is not None:
        allowed.update({"click", "input"})
        if active_policy.native_fields:
            allowed.add("select_dropdown")
    for name in list(tools.registry.registry.actions):
        if name not in allowed:
            tools.registry.exclude_action(name)
    return tools
