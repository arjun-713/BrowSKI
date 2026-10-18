"""Link and literal-field grounding on the shared task-owned Browser Use session."""

from __future__ import annotations

import hashlib
from typing import Any, cast
from urllib.parse import urljoin, urlsplit, urlunsplit

from browser_agent.engines.browser_use_runtime import ManagedBrowser, is_http_url
from browser_agent.engines.fast_contract import Candidate, FastObservation, Operation
from browser_agent.engines.general_tools import InteractionPolicy, navigation_tools
from browser_agent.engines.lifecycle import ApprovalHandler
from browser_agent.engines.native_fields import (
    FieldExecution,
    native_field_state,
    resolve_native_option,
    validate_native_date,
)
from browser_agent.task_literals import normalize_field_label, quoted_field_values


class FastBrowser(ManagedBrowser):
    def __init__(
        self, *, chrome_path: str = "/usr/bin/google-chrome", headless: bool = True
    ) -> None:
        super().__init__(chrome_path=chrome_path, headless=headless)
        self._targets: dict[str, Any] = {}
        self._input_values: dict[str, str] = {}
        self._field_operations: dict[str, Operation] = {}
        self._field_values: dict[str, str] = {}
        self._verified_fields: set[str] = set()
        self._input_policy: InteractionPolicy | None = None
        self._input_tools: Any = None

    def enable_fields(self, goal: str, approve: ApprovalHandler | None) -> None:
        assert self.browser is not None
        self._field_values = quoted_field_values(goal, strict=True)
        if self._field_values and approve is not None:
            self.browser.browser_profile.highlight_elements = False
            self._input_policy = InteractionPolicy(
                goal=goal,
                approve=approve,
                native_fields=True,
                values_by_label=dict(self._field_values),
            )
            self._input_tools = navigation_tools(self._input_policy)

    @property
    def fields_verified(self) -> bool:
        return self._verified_fields == set(self._field_values)

    @property
    def input_unavailable(self) -> bool:
        return bool(self._field_values) and self._input_tools is None

    @property
    def input_blocked_reason(self) -> str | None:
        return self._input_policy.blocked_reason if self._input_policy is not None else None

    async def observe_links(self, allowed_hosts: set[str]) -> FastObservation:
        """Fresh links plus explicitly enabled, user-literal-bound native fields."""
        assert self.browser is not None
        state = await self.browser.get_browser_state_summary(include_screenshot=False, cached=False)
        candidates: list[Candidate] = []
        destinations: list[str] = []
        self._targets.clear()
        self._input_values.clear()
        self._field_operations.clear()
        # A field verified on an earlier page may have disappeared or changed.
        # Completion requires every assignment in this observation, not history.
        self._verified_fields.clear()
        for node in state.dom_state.selector_map.values():
            if node.tag_name != "a" or node.attributes.get("aria-disabled") == "true":
                continue
            try:
                href = urljoin(state.url, node.attributes.get("href", ""))
                if not is_http_url(href):
                    continue
                destination = urlsplit(href)
            except ValueError:
                continue
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
                href=urlunsplit((destination.scheme, destination.netloc, destination.path, "", ""))[
                    :500
                ],
            )
            candidates.append(candidate)
            destinations.append(f"{candidate.id}:{href}")
            self._targets[candidate.id] = node
        fields: dict[str, list[Any]] = {}
        for node in state.dom_state.selector_map.values():
            if node.tag_name not in {"input", "textarea", "select"}:
                continue
            label = node.ax_node.name if node.ax_node is not None else ""
            key = normalize_field_label(label or "")
            if key in self._field_values:
                fields.setdefault(key, []).append(node)
        for key, nodes in fields.items():
            if len(nodes) != 1:
                continue
            node = nodes[0]
            desired = self._field_values[key]
            native = await native_field_state(
                self.browser, node, None if node.tag_name == "select" else desired
            )
            if native is None:
                continue
            destinations.append(f"field:{node.backend_node_id}:{native.model_dump_json()}")
            if native.kind == "date":
                validate_native_date(desired)
            operation = Operation.TYPE_TEXT
            token = desired
            matched = native.value == desired and native.valid
            role = "date" if native.kind == "date" else "textbox"
            current = native.value
            if native.kind.startswith("select"):
                choice = resolve_native_option(native, desired)
                if choice is None:
                    continue
                token, option = choice
                matched = native.valid and option.selected and native.value == option.value
                operation = Operation.SELECT
                role = "combobox"
                current = next((item.label for item in native.options if item.selected), current)
            elif native.proposed_valid is not True:
                continue
            if matched:
                self._verified_fields.add(key)
                continue
            if self._input_tools is None or native.disabled or native.read_only:
                continue
            candidate = Candidate(
                id=f"n{node.backend_node_id}",
                operation=operation,
                label=(node.ax_node.name or key)[:500],
                role=role,
                value=current[:256],
            )
            candidates.append(candidate)
            self._targets[candidate.id] = node
            self._input_values[candidate.id] = token
            self._field_operations[candidate.id] = operation
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
            [
                state.url,
                state.title,
                text,
                *[c.model_dump_json() for c in candidates],
                *destinations,
            ]
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

    async def set_observed(self, candidate_id: str, operation: Operation) -> FieldExecution:
        """Return whether the bound field operation ran and its native state was verified."""
        assert self.browser is not None
        if (
            self._input_tools is None
            or candidate_id not in self._input_values
            or self._field_operations.get(candidate_id) is not operation
        ):
            raise ValueError("Text target has no user-supplied literal or approval support.")
        node = self._targets[candidate_id]
        selector_map = await self.browser.get_selector_map()
        matches = [
            index
            for index, current in selector_map.items()
            if current.backend_node_id == node.backend_node_id
            and current.target_id == node.target_id
        ]
        if len(matches) != 1:
            raise ValueError("The text target is no longer uniquely grounded.")
        action_type = self._input_tools.registry.create_action_model()
        name = "select_dropdown" if operation is Operation.SELECT else "input"
        params = {"index": matches[0], "text": self._input_values[candidate_id]}
        if operation is Operation.TYPE_TEXT:
            params["clear"] = True
        action = action_type.model_validate({name: params})
        result = await self._input_tools.act(action, self.browser)
        metadata = cast(dict[str, object], result.metadata or {})
        invoked = metadata.get("browski_executed", True) is not False
        verified = not result.error and metadata.get("browski_verified") is True
        return FieldExecution(invoked, verified, metadata.get("browski_reacquired") is True)
