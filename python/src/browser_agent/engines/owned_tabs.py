"""Fresh views and verified focus changes inside one task-owned Browser Use session."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

from browser_agent.engines.browser_use_runtime import is_http_url, read_page_evidence
from browser_agent.engines.contracts import PageEvidence

MAX_TASK_TABS = 8


class TabStateChanged(RuntimeError):
    def __init__(self, *, invoked: bool = False) -> None:
        super().__init__("The task's owned tab state changed; reacquire it before acting.")
        self.invoked = invoked


@dataclass(frozen=True)
class OwnedTab:
    target_id: str
    evidence: PageEvidence


@dataclass(frozen=True)
class TabSnapshot:
    active_id: str
    tabs: tuple[OwnedTab, ...]
    fingerprint: str


async def observe_owned_tabs(browser: Any, allowed_hosts: set[str]) -> TabSnapshot:
    from browser_use.actor.page import Page

    targets = sorted(browser.get_page_targets(), key=lambda target: str(target.target_id))
    if len(targets) > MAX_TASK_TABS:
        raise ValueError("Task exceeds the eight-tab limit; no owned tabs were truncated.")
    active = browser.get_focused_target()
    if active is None:
        raise TabStateChanged()
    active_id = str(active.target_id)
    tabs: list[OwnedTab] = []
    for target in targets:
        target_id = str(target.target_id)
        page = Page(browser, target_id)
        try:
            info = await page.get_target_info()
            url = info.get("url", "")
            if not is_http_url(url) or urlsplit(url).hostname not in allowed_hosts:
                continue
            if await cast(Any, page).evaluate("() => document.readyState") == "loading":
                raise TabStateChanged()
            evidence = await read_page_evidence(page)
        except TabStateChanged:
            raise
        except Exception as error:
            # The target list can race a popup closing. Reads are retryable;
            # preserve the cause and let the task's existing bound decide.
            raise TabStateChanged() from error
        if is_http_url(evidence.url) and urlsplit(evidence.url).hostname in allowed_hosts:
            tabs.append(OwnedTab(target_id, evidence))
    current = browser.get_focused_target()
    if current is None or str(current.target_id) != active_id:
        raise TabStateChanged()
    payload = json.dumps(
        {
            "active": active_id,
            "targets": [str(target.target_id) for target in targets],
            "pages": [{"target": tab.target_id, "page": tab.evidence.model_dump()} for tab in tabs],
        },
        sort_keys=True,
    )
    return TabSnapshot(active_id, tuple(tabs), hashlib.sha256(payload.encode()).hexdigest())


async def focus_owned_tab(browser: Any, tab: OwnedTab) -> None:
    from browser_use.browser.events import SwitchTabEvent

    if tab.target_id not in {str(target.target_id) for target in browser.get_page_targets()}:
        raise TabStateChanged()
    event = browser.event_bus.dispatch(SwitchTabEvent(target_id=tab.target_id))
    try:
        await event
        await event.event_result(raise_if_any=True)
        current = browser.get_focused_target()
        page = await browser.get_current_page()
        if current is None or str(current.target_id) != tab.target_id or page is None:
            raise TabStateChanged(invoked=True)
        evidence = await read_page_evidence(page)
        if evidence.url != tab.evidence.url:
            raise TabStateChanged(invoked=True)
    except TabStateChanged:
        raise
    except Exception as error:
        raise TabStateChanged(invoked=True) from error
