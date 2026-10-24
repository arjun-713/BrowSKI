"""One explicit, task-local source value with fresh owned-page provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast

from browser_agent.engines.browser_use_runtime import is_http_url
from browser_agent.engines.owned_tabs import TabSnapshot
from browser_agent.providers.privacy import (
    has_recognized_sensitive_content,
    has_recognized_sensitive_label,
)
from browser_agent.task_literals import MAX_VALUE_CHARS, TaskLiteralError, normalize_field_label

# Fixed browser-owned projection. Labels are arguments, never interpolated code.
# Keep only a unique visible static fact: definition lists, two-cell table rows,
# named static text or an exact label/delimiter/value block. No controls/editors,
# hidden ancestors, iframe content, arbitrary page instructions or model values.
_READ_SOURCE = r"""(label) => {
    const norm = s => s.normalize('NFKC').toLowerCase().replace(/\s+/g,' ').trim();
    const visible = e => e && e.isConnected && e.getClientRects().length > 0 &&
        e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) &&
        !e.closest('[hidden],[aria-hidden="true"],[inert],input,textarea,select,' +
          'button,a,[contenteditable]:not([contenteditable="false"]),[role="textbox"]');
    const entries = [];
    const represented = new Set();
    const add = (element, value, context) => {
        if (!visible(element) || !visible(context)) return;
        if (element.querySelector('input,textarea,select,button,a,[contenteditable],' +
            '[hidden],[aria-hidden="true"],[inert]')) return;
        entries.push({value:value.trim(), html:context.outerHTML});
        represented.add(element);
    };
    const nodes = document.querySelectorAll('dt,tr,[aria-label],p,div,span,li,td,dd');
    if (nodes.length > 5000 || document.documentElement.outerHTML.length > 1000000)
        return null;
    for (const node of nodes) {
        if (!visible(node) || represented.has(node)) continue;
        if (node.tagName === 'DT' && norm(node.innerText) === norm(label)) {
            const value = node.nextElementSibling;
            if (value?.tagName === 'DD' && value.nextElementSibling?.tagName !== 'DD')
                add(value, value.innerText, node.parentElement);
        } else if (node.tagName === 'TR' && node.cells.length === 2 &&
                   norm(node.cells[0].innerText) === norm(label)) {
            add(node.cells[1], node.cells[1].innerText, node);
        } else if (norm(node.getAttribute('aria-label') || '') === norm(label)) {
            if (!node.querySelector('input,textarea,select,button,a,[contenteditable]'))
                add(node, node.innerText, node);
        } else if (![...represented].some(e => e.contains(node)) &&
                   !node.querySelector('dt,tr,[aria-label],p,div,li')) {
            const text = node.innerText.trim();
            const separator = text.search(/[:=–—]/);
            if (separator > 0 && norm(text.slice(0,separator)) === norm(label))
                add(node, text.slice(separator+1), node);
        }
    }
    if (entries.length !== 1 || entries[0].html.length > 100000) return null;
    return JSON.stringify({url:location.href, epoch:performance.timeOrigin,
        value:entries[0].value, html:entries[0].html});
}"""


@dataclass(frozen=True)
class SourceFact:
    target_id: str
    url: str
    value: str
    fingerprint: str


class SourceTransfer:
    """A single explicit transfer, scoped to the task's original destination tab.

    Capture requires visiting a distinct owned supporting tab. After capture,
    any source change invalidates authority for this task; it cannot silently
    replace the value during a human approval wait. No durable/source dump exists.
    """

    def __init__(self, labels: tuple[str, str]) -> None:
        if any(has_recognized_sensitive_label(label) for label in labels):
            raise TaskLiteralError("Sensitive source or destination labels are not supported.")
        self.source_label, destination = labels
        self.destination_label = normalize_field_label(destination)
        self.destination_target: str | None = None
        self.fact: SourceFact | None = None
        self.error: str | None = None

    @property
    def value(self) -> str | None:
        return self.fact.value if self.fact is not None and self.error is None else None

    @property
    def fingerprint(self) -> str:
        if self.fact is None:
            return "source:missing"
        return f"source:{self.fact.target_id}:{self.fact.fingerprint}:{self.error}"

    def matches_input(self, label: str, value: str, target_id: str) -> bool:
        return (
            self.value is not None
            and target_id == self.destination_target
            and normalize_field_label(label) == self.destination_label
            and value == self.value
        )

    async def observe(self, browser: Any, tabs: TabSnapshot) -> None:
        if self.destination_target is None:
            self.destination_target = tabs.active_id
        if self.fact is not None:
            await self.verify(browser)
            return
        if tabs.active_id == self.destination_target or self.error is not None:
            return
        active = next((tab for tab in tabs.tabs if tab.target_id == tabs.active_id), None)
        if active is not None:
            fact = await self._read(browser, active.target_id)
            if fact is not None and fact.url == active.evidence.url:
                self.fact = fact

    async def verify(self, browser: Any) -> bool:
        if self.fact is None or self.error is not None:
            return False
        current = await self._read(browser, self.fact.target_id)
        if current != self.fact:
            self.error = (
                "The supporting source changed or closed; its value is no longer authorized."
            )
            return False
        return True

    async def _read(self, browser: Any, target_id: str) -> SourceFact | None:
        from browser_use.actor.page import Page

        if target_id not in {str(target.target_id) for target in browser.get_page_targets()}:
            return None
        try:
            raw = await cast(Any, Page(browser, target_id)).evaluate(
                _READ_SOURCE, self.source_label
            )
            if not raw or raw == "null":
                return None
            data = cast(dict[str, Any], json.loads(raw))
            value = data.get("value")
            url = data.get("url")
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > MAX_VALUE_CHARS
                or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value)
                or has_recognized_sensitive_content(value)
                or not is_http_url(url)
            ):
                return None
            return SourceFact(target_id, str(url), value, hashlib.sha256(raw.encode()).hexdigest())
        except Exception as error:
            # Missing/detached source reads never authorize a write. Preserve a
            # safe failure class rather than logging page data or source values.
            self.error = (
                f"Supporting source read failed ({type(error).__name__}); no value authorized."
            )
            return None
