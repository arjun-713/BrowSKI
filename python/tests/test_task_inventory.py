"""Task inventory exports only exact, task-approved browser facts."""

from __future__ import annotations

from typing import cast

import pytest

from browser_agent._types import SemanticSnapshot, TabInfo, TaskState, VerifiedLinkOpen
from browser_agent.agent.task_inventory import TaskInventory
from browser_agent.session import BrowserSession


class FakeBrowser:
    def __init__(self, tabs: list[TabInfo]) -> None:
        self.current_tabs = tabs
        self.calls = 0

    async def tabs(self) -> list[TabInfo]:
        self.calls += 1
        return list(self.current_tabs)


def snapshot(*tab_ids: str) -> SemanticSnapshot:
    active_tab = tab_ids[0] if tab_ids else None
    return SemanticSnapshot(
        url="https://start.example/",
        active_tab=active_tab,
        tabs=list(tab_ids),
        state_generation=4,
        page_fingerprint="inventory-test-page",
    )


def tab(tab_id: str, url: str, title: str = "private title") -> TabInfo:
    return TabInfo(id=tab_id, target=f"target-{tab_id}", url=url, title=title)


def bind(inventory: TaskInventory, browser: FakeBrowser) -> None:
    inventory.bind_browser(cast(BrowserSession, browser))


@pytest.mark.asyncio
async def test_only_exact_requested_destination_gets_label_and_proof() -> None:
    browser = FakeBrowser(
        [
            tab("start", "https://start.example/"),
            tab("requested", "https://destination.example/product"),
            tab("same-host-other-path", "https://destination.example/unrelated"),
            tab("other", "https://private.example/path"),
        ]
    )
    inventory = TaskInventory()
    bind(inventory, browser)
    task = TaskState(task='Open "https://destination.example/product" in a new tab')

    current = snapshot("start", "requested", "same-host-other-path", "other")
    await inventory.refresh(current, task, {})

    assert inventory.task_tab_labels == {"requested": "task destination 1"}
    assert inventory.destination_checks == {"owned_task_destination:1": True}
    assert task.deterministic_evidence == ["owned_task_destination:1"]
    assert "private title" not in str(inventory.task_tab_labels)
    assert "private.example" not in str(inventory.task_tab_labels | inventory.destination_checks)


@pytest.mark.asyncio
async def test_each_requested_url_needs_an_exact_owned_tab() -> None:
    browser = FakeBrowser(
        [
            tab("start", "https://start.example/"),
            tab("one", "https://one.example/page/"),
            tab("redirected", "https://two.example/redirected"),
        ]
    )
    inventory = TaskInventory()
    bind(inventory, browser)
    task = TaskState(
        task=(
            'Open the exact pages "https://one.example/page" and '
            '"https://two.example/page" in separate browser tabs'
        )
    )

    await inventory.refresh(snapshot("start", "one", "redirected"), task, {})

    assert inventory.destination_checks == {
        "owned_task_destination:1": True,
        "owned_task_destination:2": False,
    }
    assert task.deterministic_evidence == ["owned_task_destination:1"]


@pytest.mark.asyncio
async def test_stale_destination_facts_are_removed_when_tab_url_changes() -> None:
    browser = FakeBrowser(
        [
            tab("start", "https://start.example/"),
            tab("target", "https://wanted.example/page"),
        ]
    )
    inventory = TaskInventory()
    bind(inventory, browser)
    task = TaskState(task='Open "https://wanted.example/page" in a new tab')
    current = snapshot("start", "target")

    await inventory.refresh(current, task, {})
    assert task.deterministic_evidence == ["owned_task_destination:1"]

    browser.current_tabs[1] = tab("target", "https://other.example/page")
    await inventory.refresh(current, task, {})

    assert inventory.destination_checks == {"owned_task_destination:1": False}
    assert task.deterministic_evidence == []


@pytest.mark.asyncio
async def test_no_browser_clears_prior_inventory_and_owned_proof_without_error() -> None:
    inventory = TaskInventory()
    browser = FakeBrowser([tab("target", "https://wanted.example/page")])
    bind(inventory, browser)
    task = TaskState(
        task='Open "https://wanted.example/page" in a new tab',
        deterministic_evidence=["unrelated-proof", "owned_task_destination:1"],
    )
    await inventory.refresh(snapshot("target"), task, {})
    assert inventory.destination_checks["owned_task_destination:1"]

    unbound = TaskInventory()
    await unbound.refresh(snapshot("target"), task, {})

    assert unbound.owned_tab_urls == {}
    assert unbound.task_tab_labels == {}
    assert unbound.destination_checks == {}
    assert task.deterministic_evidence == ["unrelated-proof"]


@pytest.mark.asyncio
async def test_duplicate_requested_urls_produce_one_destination_fact() -> None:
    requested = "https://duplicate.example/page"
    browser = FakeBrowser([tab("target", requested)])
    inventory = TaskInventory()
    bind(inventory, browser)
    task = TaskState(task=f'Open "{requested}" in a new tab, then open "{requested}" in a new tab')

    await inventory.refresh(snapshot("target"), task, {})

    assert inventory.destination_checks == {"owned_task_destination:1": True}
    assert inventory.task_tab_labels == {"target": "task destination 1"}


@pytest.mark.asyncio
async def test_configured_alias_is_only_labeled_at_exact_configured_destination() -> None:
    browser = FakeBrowser(
        [
            tab("home", "https://shop.example/"),
            tab("other-path", "https://shop.example/catalog/item"),
        ]
    )
    inventory = TaskInventory()
    bind(inventory, browser)
    task = TaskState(task="Search for a laptop on Shop")

    await inventory.refresh(
        snapshot("home", "other-path"),
        task,
        {"shop": "https://shop.example/"},
    )

    assert inventory.task_tab_labels == {"home": "shop"}
    assert inventory.destination_checks == {"owned_task_destination:1": True}


@pytest.mark.asyncio
async def test_verified_source_link_label_is_exposed_only_for_current_owned_tab() -> None:
    browser = FakeBrowser(
        [
            tab("origin", "https://source.example/"),
            tab("orbit", "https://product.example/orbit"),
        ]
    )
    inventory = TaskInventory()
    bind(inventory, browser)
    task = TaskState(
        task="Open each product link in separate tabs.",
        required_link_source_tab_id="origin",
        required_link_source_generation=4,
        required_link_source_fingerprint="inventory-test-page",
        required_link_refs=["@orbit", "@field"],
        verified_link_opens=[
            VerifiedLinkOpen(
                source_tab_id="origin",
                source_ref="@orbit",
                source_generation=4,
                source_page_fingerprint="inventory-test-page",
                opened_tab_id="orbit",
                link_label="Orbit 14 details",
            ),
            VerifiedLinkOpen(
                source_tab_id="other-source",
                source_ref="@intruder",
                source_generation=4,
                source_page_fingerprint="inventory-test-page",
                opened_tab_id="orbit",
                link_label="Unrelated tab label",
            ),
        ],
    )

    await inventory.refresh(snapshot("origin", "orbit"), task, {})

    assert inventory.task_tab_labels == {
        "origin": "Source page with requested links",
        "orbit": "Orbit 14 details",
    }
