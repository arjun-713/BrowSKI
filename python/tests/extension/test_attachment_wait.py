"""The native bridge can receive an attach message after the UI click returns."""

import asyncio
from pathlib import Path

import pytest

from browser_agent.extension.service import ExtensionBridgeService


class _BrowserStub:
    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_bounded_wait_allows_a_dispatched_attachment_to_arrive(tmp_path: Path) -> None:
    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    browser = _BrowserStub()
    waiter = asyncio.create_task(service.wait_for_attached_browser(wait_seconds=1))
    await asyncio.sleep(0)
    assert not waiter.done()

    async def initialize() -> None:
        service._browser_session = browser  # pyright: ignore[reportPrivateUsage]

    owner = asyncio.create_task(initialize())
    service._attachment_task = owner  # pyright: ignore[reportPrivateUsage]
    service._attachment_started.set()  # pyright: ignore[reportPrivateUsage]
    try:
        assert await waiter is browser
        await owner
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_attachment_wait_timeout_does_not_cancel_service_owner(tmp_path: Path) -> None:
    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    release = asyncio.Event()

    async def initialize() -> None:
        await release.wait()

    owner = asyncio.create_task(initialize())
    service._attachment_task = owner  # pyright: ignore[reportPrivateUsage]
    try:
        assert await service.wait_for_attached_browser(wait_seconds=0.01) is None
        assert not owner.done()
        release.set()
        await owner
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_unattached_default_is_immediate_and_explicit_wait_is_bounded(tmp_path: Path) -> None:
    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    assert await service.wait_for_attached_browser() is None
    assert await service.wait_for_attached_browser(wait_seconds=0.01) is None
    with pytest.raises(ValueError, match="timeout"):
        await service.wait_for_attached_browser(wait_seconds=31)
    await service.close()
