"""Packaged Chrome: real Browser Use drives a user tab through the extension relay.

No model is involved. This proves the transport ADR-032 relies on: browser-level
emulation, per-tab forwarding, flat child sessions, opener tabs and clean release.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import pytest

from browser_agent.extension.install import install_native_host
from browser_agent.extension.service import ExtensionBridgeService

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("BROWSKI_EXTENSION_E2E") != "1",
        reason="set BROWSKI_EXTENSION_E2E=1 to launch a real extension browser",
    ),
]

_PAGES = {
    "index.html": """<!doctype html><title>Relay start</title>
<h1>Relay start</h1>
<label>Search <input id="q" name="q" aria-label="Search"></label>
<button id="go" onclick="document.getElementById('out').textContent='Searched '+q.value">
Go</button>
<p id="out"></p>
<a href="/next.html">Next page</a>
<a href="/popup.html" target="_blank">Open help</a>
<iframe src="FRAME_URL" title="Partner widget" width="400" height="120"></iframe>""",
    "next.html": "<!doctype html><title>Next</title><h1>Second page</h1>",
    "popup.html": "<!doctype html><title>Help</title><h1>Help centre</h1>",
    "frame.html": "<!doctype html><title>Frame</title><button>Partner button</button>",
}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


@pytest.fixture
def fixture_site(tmp_path: Path) -> Iterator[str]:
    root = tmp_path / "site"
    root.mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    port = server.server_port
    # localhost and 127.0.0.1 are different sites, so the iframe is an OOPIF.
    for name, html in _PAGES.items():
        (root / name).write_text(html.replace("FRAME_URL", f"http://localhost:{port}/frame.html"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@dataclass(frozen=True)
class RelayHarness:
    service: ExtensionBridgeService
    context: Any
    worker: Any
    start_url: str


@pytest.fixture
async def relay_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_site: str
) -> AsyncIterator[RelayHarness]:
    from playwright.async_api import async_playwright

    from .test_browser_e2e import (
        FixtureCredentialStore,
        _extension_worker,  # pyright: ignore[reportPrivateUsage]
        _launch_extension_context,  # pyright: ignore[reportPrivateUsage]
    )

    root = Path(__file__).parents[3]
    extension_path = Path(
        os.environ.get("BROWSKI_EXTENSION_OUTPUT", root / "extension" / ".output" / "chrome-mv3")
    )
    host_executable = root / "python" / ".venv" / "bin" / "browski-native-host"
    assert (extension_path / "manifest.json").is_file(), "build the extension first"
    runtime_socket = tmp_path / "runtime" / "bridge.sock"
    config_path = tmp_path / "browski.toml"
    default_config = root / "python" / "src" / "browser_agent" / "cli" / "default.toml"
    config_path.write_text(
        default_config.read_text().replace('mode = "shadow"', 'mode = "disabled"')
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("BROWSKI_RUNTIME_SOCKET", str(runtime_socket))
    environment = {**os.environ, "BROWSKI_RUNTIME_SOCKET": str(runtime_socket)}
    service = ExtensionBridgeService(
        runtime_socket,
        config_path=config_path,
        database_path=tmp_path / "checkpoints.sqlite",
        credential_store=FixtureCredentialStore(),
    )
    await service.start()
    try:
        async with async_playwright() as playwright:
            profile = tmp_path / "profile"
            first = await _launch_extension_context(
                playwright, profile=profile, extension_path=extension_path, environment=environment
            )
            try:
                extension_id = urlsplit((await _extension_worker(first)).url).hostname
            finally:
                await first.close()
            assert extension_id is not None
            install_native_host(
                extension_id=extension_id,
                browser="chromium",
                host_executable=host_executable,
                manifest_directory=profile / "NativeMessagingHosts",
            )
            context = await _launch_extension_context(
                playwright, profile=profile, extension_path=extension_path, environment=environment
            )
            try:
                worker = await _extension_worker(context)
                start = context.pages[0] if context.pages else await context.new_page()
                await start.goto(fixture_site)
                panel = await context.new_page()
                await panel.goto(f"chrome-extension://{extension_id}/panel.html")
                await panel.evaluate("chrome.runtime.sendMessage({type: 'host.connect'})")
                await _until(lambda: service.runtime_session is not None, "runtime handshake")
                await start.bring_to_front()
                await worker.evaluate(
                    """async (url) => {
                      const [tab] = await chrome.tabs.query({url});
                      await chrome.tabs.update(tab.id, {active: true});
                      await chrome.windows.update(tab.windowId, {focused: true});
                    }""",
                    fixture_site + "*",
                )
                yield RelayHarness(service, context, worker, fixture_site)
            finally:
                await context.close()
    finally:
        await service.close()


async def _until(condition: Any, what: str, limit_seconds: float = 15) -> None:
    deadline = asyncio.get_running_loop().time() + limit_seconds
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.1)


def _node(state: Any, attribute: str, value: str) -> Any:
    nodes: list[Any] = list(state.dom_state.selector_map.values())
    return next(node for node in nodes if node.attributes.get(attribute) == value)


async def test_browser_use_drives_the_users_tab_through_the_relay(
    relay_harness: RelayHarness,
) -> None:
    from browser_use import BrowserSession
    from browser_use.browser.events import (
        ClickElementEvent,
        CloseTabEvent,
        NavigateToUrlEvent,
        SendKeysEvent,
        SwitchTabEvent,
        TypeTextEvent,
    )

    harness = relay_harness
    async with harness.service.agent_relay.lease() as lease:
        session = BrowserSession(cdp_url=lease.cdp_url, keep_alive=True, highlight_elements=False)
        await asyncio.wait_for(session.start(), timeout=30)
        try:
            state = await session.get_browser_state_summary()
            assert state.url == harness.start_url
            assert len(state.tabs) == 1, "only the leased tab is visible to the agent"
            search = _node(state, "id", "q")
            frame_button = [
                n
                for n in state.dom_state.selector_map.values()
                if "Partner button" in n.get_all_children_text()
            ]
            assert frame_button, "cross-site iframe content reached through a child session"

            await session.event_bus.dispatch(TypeTextEvent(node=search, text="relay test"))
            await session.event_bus.dispatch(SendKeysEvent(keys="Enter"))
            state = await session.get_browser_state_summary()
            go = _node(state, "id", "go")
            await session.event_bus.dispatch(ClickElementEvent(node=go))
            state = await session.get_browser_state_summary()
            assert "Searched relay test" in state.dom_state.llm_representation()

            popup_link = _node(state, "target", "_blank")
            await session.event_bus.dispatch(ClickElementEvent(node=popup_link))
            await _until(lambda: len(session.session_manager.get_all_page_targets()) == 2, "popup")
            tabs = await session.get_tabs()
            popup = next(tab for tab in tabs if tab.url.endswith("/popup.html"))
            await session.event_bus.dispatch(SwitchTabEvent(target_id=popup.target_id))
            state = await session.get_browser_state_summary()
            assert state.title == "Help"

            screenshot: object = await cast(Any, session).take_screenshot()
            assert screenshot

            await session.event_bus.dispatch(CloseTabEvent(target_id=popup.target_id))
            await _until(lambda: len(session.session_manager.get_all_page_targets()) == 1, "close")
            # As in an agent step, focus recovery (via activateTarget) precedes the next action.
            await _until(lambda: session.agent_focus_target_id is not None, "focus recovery")
            await session.event_bus.dispatch(
                NavigateToUrlEvent(url=harness.start_url + "next.html")
            )
            state = await session.get_browser_state_summary()
            assert state.title == "Next"
        finally:
            await session.stop()
    pages = [page.url for page in harness.context.pages]
    assert harness.start_url + "next.html" in pages, "the user's tab stays open"
    # Re-attaching only succeeds once the relay released its own debugger session.
    # (getTargets().attached also counts Playwright's connection, so it cannot be used.)
    reattached = await harness.worker.evaluate(
        """async (url) => {
          const [tab] = await chrome.tabs.query({url});
          await chrome.debugger.attach({tabId: tab.id}, "1.3");
          await chrome.debugger.detach({tabId: tab.id});
          return true;
        }""",
        harness.start_url + "*",
    )
    assert reattached is True, "the debugger is released when the task ends"
    assert not harness.service.agent_relay.active
