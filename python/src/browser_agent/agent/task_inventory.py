"""Local, task-scoped inventory facts for browser tabs and destinations."""

from __future__ import annotations

from collections.abc import Mapping

from browser_agent._types import SemanticSnapshot, TabInfo, TaskState
from browser_agent.decisions.task_sites import (
    destination_task,
    normalize_task_url,
    requested_sites,
    task_tab_labels,
)
from browser_agent.decisions.task_tabs import explicit_task_destinations
from browser_agent.session import BrowserSession

_DESTINATION_FACT_PREFIX = "owned_task_destination:"


class TaskInventory:
    """Keep raw tab URLs local; expose only task-approved aliases and proofs."""

    def __init__(self) -> None:
        self._browser: BrowserSession | None = None
        self._owned_tab_urls: dict[str, str] = {}
        self._task_tab_labels: dict[str, str] = {}
        self._destination_checks: dict[str, bool] = {}

    @property
    def owned_tab_urls(self) -> dict[str, str]:
        """Return a local copy for candidate deduplication and owned-tab checks."""
        return dict(self._owned_tab_urls)

    @property
    def task_tab_labels(self) -> dict[str, str]:
        return dict(self._task_tab_labels)

    @property
    def destination_checks(self) -> dict[str, bool]:
        return dict(self._destination_checks)

    def bind_browser(self, browser: BrowserSession) -> None:
        self._browser = browser
        self._clear_inventory()

    async def refresh(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        site_aliases: Mapping[str, str],
    ) -> None:
        """Refresh from currently owned tabs and replace stale task proofs."""
        goal = task.user_goal or task.task
        if self._browser is None:
            self._clear_inventory()
            self._replace_task_evidence(task, {})
            return

        tabs: list[TabInfo] = await self._browser.tabs()
        owned = {tab.id: tab.url for tab in tabs if tab.id in snapshot.tabs}
        sites = requested_sites(goal, site_aliases)
        self._owned_tab_urls = owned

        inventory_goal = destination_task(goal, sites)
        destinations = explicit_task_destinations(inventory_goal)
        self._task_tab_labels = task_tab_labels(inventory_goal, sites, owned)
        checks: dict[str, bool] = {}
        for index, wanted in enumerate(destinations, start=1):
            normalized_wanted = normalize_task_url(wanted)
            checks[f"{_DESTINATION_FACT_PREFIX}{index}"] = bool(normalized_wanted) and any(
                normalize_task_url(actual) == normalized_wanted for actual in owned.values()
            )
        self._destination_checks = checks
        self._replace_task_evidence(task, checks)

    def _clear_inventory(self) -> None:
        self._owned_tab_urls.clear()
        self._task_tab_labels.clear()
        self._destination_checks.clear()

    @staticmethod
    def _replace_task_evidence(task: TaskState, checks: Mapping[str, bool]) -> None:
        previous = {
            value
            for value in task.deterministic_evidence
            if value.startswith(_DESTINATION_FACT_PREFIX)
        }
        observed = {key for key, present in checks.items() if present}
        task.deterministic_evidence = [
            value
            for value in task.deterministic_evidence
            if not value.startswith(_DESTINATION_FACT_PREFIX)
        ][-22:] + sorted(observed)
        if observed - previous:
            task.stagnant_steps = 0
            if "required_fact_acquired" not in task.progress_signals:
                task.progress_signals.append("required_fact_acquired")
