"""Vertical-slice smoke test: launch Chromium, navigate, observe, close.

Requires a Chrome/Chromium binary; page contents come from local fixtures.
"""

from pathlib import Path

import pytest

from browser_agent import BrowserSession

pytestmark = pytest.mark.asyncio
FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/m2/native-form.html"


async def test_navigate_and_observe_local_fixture() -> None:
    async with BrowserSession.launch() as browser:
        assert browser.session_id is not None
        await browser.navigate(FIXTURE.as_uri())
        snapshot = await browser.observe()
        assert snapshot.url.startswith("file://"), snapshot.url
        assert snapshot.title == "Native form"
        assert snapshot.state_generation >= 1


async def test_capture_viewport_screenshot_returns_bounded_png() -> None:
    async with BrowserSession.launch() as browser:
        await browser.navigate(FIXTURE.as_uri())
        await browser.observe()
        tab_id = await browser.active_tab_id()
        assert tab_id is not None

        screenshot = await browser.capture_viewport_screenshot(tab_id)

        assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(screenshot) <= 4 * 1024 * 1024


async def test_m2_render_delta_and_resolve() -> None:
    """M2 Python surface: tabs, render, empty delta, alias resolution."""
    async with BrowserSession.launch() as browser:
        await browser.navigate(FIXTURE.as_uri())
        await browser.observe()
        tab_id = await browser.active_tab_id()
        assert tab_id is not None
        tabs = await browser.tabs()
        assert any(t.id == tab_id for t in tabs)

        text = await browser.render_observation(tab_id)
        assert "@" in text, f"render:\n{text}"
        assert "application" in text.lower(), f"render:\n{text}"

        # No page change between observes: delta is empty.
        await browser.observe()
        delta = await browser.observe_delta(tab_id)
        assert delta.added == [] and delta.removed == [] and delta.changed == []

        # First @ref in the render resolves to a registry identity.
        first_ref = next(line for line in text.splitlines() if line.startswith("@"))
        resolved = await browser.resolve(tab_id, first_ref)
        assert resolved is not None
        assert resolved.ref == first_ref
        assert resolved.generation >= 1
        assert await browser.resolve(tab_id, "@nope_missing") is None
