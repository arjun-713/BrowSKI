"""Fast navigation grounding on the shared task-owned Browser Use session."""

from __future__ import annotations

import hashlib
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

from browser_agent.engines.browser_use_runtime import ManagedBrowser
from browser_agent.engines.fast_contract import Candidate, FastObservation, Operation


class FastBrowser(ManagedBrowser):
    def __init__(
        self, *, chrome_path: str = "/usr/bin/google-chrome", headless: bool = True
    ) -> None:
        super().__init__(chrome_path=chrome_path, headless=headless)
        self._targets: dict[str, Any] = {}

    async def observe_links(self, allowed_hosts: set[str]) -> FastObservation:
        """Use Browser Use DOM/AX semantics; initial Fast scope is link navigation."""
        assert self.browser is not None
        state = await self.browser.get_browser_state_summary(include_screenshot=False, cached=False)
        candidates: list[Candidate] = []
        self._targets.clear()
        for node in state.dom_state.selector_map.values():
            if node.tag_name != "a" or node.attributes.get("aria-disabled") == "true":
                continue
            href = urljoin(state.url, node.attributes.get("href", ""))
            destination = urlsplit(href)
            if (
                destination.scheme not in {"http", "https"}
                or destination.hostname not in allowed_hosts
            ):
                continue
            label = node.ax_node.name if node.ax_node is not None else ""
            label = label or node.get_all_children_text(max_depth=3)
            if not label.strip():
                continue
            candidate = Candidate(
                id=f"n{node.backend_node_id}",
                operation=Operation.CLICK,
                label=label.strip()[:500],
                role="link",
            )
            candidates.append(candidate)
            self._targets[candidate.id] = node
        if len(candidates) > 120:
            raise ValueError(
                "Page exceeds the current 120-candidate Fast limit; no targets truncated."
            )
        page = await self.browser.get_current_page()
        if page is None:
            raise ValueError("Task page disappeared during observation.")
        # Browser Use element indexes are regenerated between snapshots; they
        # cannot be part of a semantic freshness fingerprint. Read page text
        # separately, and keep backend-node identity in the candidate table.
        text = await cast(Any, page).evaluate("() => document.body.innerText.slice(0,6000)")
        payload = "\n".join(
            [state.url, state.title, text, *[c.model_dump_json() for c in candidates]]
        )
        return FastObservation(
            id=hashlib.sha256(payload.encode()).hexdigest(),
            url=state.url,
            title=state.title,
            text=text,
            candidates=tuple(candidates),
        )

    async def click_observed(self, candidate_id: str) -> None:
        assert self.browser is not None
        node = self._targets.get(candidate_id)
        if node is None:
            raise ValueError("Target is not in the fresh Browser Use observation.")
        page = await self.browser.get_current_page()
        if page is None:
            raise ValueError("The task's browser page is no longer available.")
        element = await page.get_element(node.backend_node_id)
        await element.click()
