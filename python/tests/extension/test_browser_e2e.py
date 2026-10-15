"""Opt-in Playwright smoke test for the packaged extension/runtime boundary."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit

import pytest
from playwright.async_api import BrowserContext, Page, Playwright, Worker, async_playwright, expect

from browser_agent import BrowserSession
from browser_agent._types import BrowserAction, ElementRef
from browser_agent.agent import AgentRuntime
from browser_agent.cli.config import BrowskiConfig
from browser_agent.extension.install import install_native_host
from browser_agent.extension.service import ExtensionBridgeService
from browser_agent.reasoning import ReasoningProvider

from .full_demo_reasoner import FullDemoReasoner
from .scripted_reasoner import ScriptedReasoner

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("BROWSKI_EXTENSION_E2E") != "1",
        reason="set BROWSKI_EXTENSION_E2E=1 to launch a real extension browser",
    ),
]


class QuietDemoHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


class CdpInspector(Protocol):
    """Typed subset of Playwright's otherwise untyped DevTools response API."""

    async def send(self, method: str, params: dict[str, object]) -> dict[str, object]: ...

    async def detach(self) -> None: ...


class FixtureCredentialStore:
    """Synthetic in-memory store; the real transport never receives a real key."""

    def __init__(self) -> None:
        self.value: str | None = None

    def get_openai_api_key(self) -> str | None:
        return self.value

    def set_openai_api_key(self, api_key: str) -> None:
        self.value = api_key

    def delete_openai_api_key(self) -> None:
        self.value = None


async def _extension_worker(context: BrowserContext, *, timeout_seconds: float = 10) -> Worker:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        worker = next(
            (
                item
                for item in context.service_workers
                if item.url.startswith("chrome-extension://")
            ),
            None,
        )
        if worker is not None:
            return worker
        try:
            worker = await context.wait_for_event("serviceworker", timeout=500)
        except TimeoutError:
            continue
        if worker.url.startswith("chrome-extension://"):
            return worker
    raise AssertionError("BROWSKI extension service worker did not start")


async def _launch_extension_context(
    playwright: Playwright,
    *,
    profile: Path,
    extension_path: Path,
    environment: dict[str, str],
) -> BrowserContext:
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        channel="chromium",
        headless=os.environ.get("BROWSKI_EXTENSION_HEADFUL") != "1",
        viewport={"width": 1280, "height": 900},
        env=dict[str, str | float | bool](environment),
        args=[
            f"--disable-extensions-except={extension_path}",
            f"--load-extension={extension_path}",
        ],
    )


async def _wait_for_detached(service: ExtensionBridgeService) -> None:
    # The public service exposes session state; the caller bounds this test poll.
    while service.runtime_session is not None:  # noqa: ASYNC110
        await asyncio.sleep(0.05)


@dataclass(frozen=True)
class AttachedHarness:
    service: ExtensionBridgeService
    browser: BrowserSession
    demo: Page
    panel: Page
    credentials: FixtureCredentialStore
    config_path: Path


@pytest.fixture
async def attached_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AttachedHarness]:
    root = Path(__file__).parents[3]
    extension_path = root / "extension" / ".output" / "chrome-mv3"
    host_executable = root / "python" / ".venv" / "bin" / "browski-native-host"
    config_home = tmp_path / "config"
    runtime_socket = tmp_path / "runtime" / "bridge.sock"
    fixture_root = root / "examples" / "demo_site"
    default_config = root / "python" / "src" / "browser_agent" / "cli" / "default.toml"
    config_path = tmp_path / "browski.toml"
    config_path.write_text(
        default_config.read_text().replace('mode = "shadow"', 'mode = "disabled"')
    )

    assert (extension_path / "manifest.json").is_file(), "build the extension first"
    assert host_executable.is_file(), "install the Python development extra first"
    assert (fixture_root / "index.html").is_file(), "the local demo fixture is required"

    http_server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(QuietDemoHandler, directory=str(fixture_root)),
    )
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()
    demo_url = f"http://127.0.0.1:{http_server.server_port}/"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("BROWSKI_RUNTIME_SOCKET", str(runtime_socket))
    chrome_environment = {
        **os.environ,
        "XDG_CONFIG_HOME": str(config_home),
        "BROWSKI_RUNTIME_SOCKET": str(runtime_socket),
    }
    credentials = FixtureCredentialStore()
    service = ExtensionBridgeService(
        runtime_socket,
        config_path=config_path,
        database_path=tmp_path / "checkpoints.sqlite",
        credential_store=credentials,
    )
    try:
        await service.start()
        async with async_playwright() as playwright:
            profile = tmp_path / "chromium-profile"
            first_context = await _launch_extension_context(
                playwright,
                profile=profile,
                extension_path=extension_path,
                environment=chrome_environment,
            )
            try:
                first_worker = await _extension_worker(first_context)
                extension_id = urlsplit(first_worker.url).hostname
                assert extension_id is not None
            finally:
                await first_context.close()

            install_native_host(
                extension_id=extension_id,
                browser="chromium",
                host_executable=host_executable,
                # --user-data-dir changes Chrome's user-level host lookup root.
                manifest_directory=profile / "NativeMessagingHosts",
            )

            context = await _launch_extension_context(
                playwright,
                profile=profile,
                extension_path=extension_path,
                environment=chrome_environment,
            )
            context.set_default_timeout(10_000)
            worker = await _extension_worker(context)
            demo_page = context.pages[0] if context.pages else await context.new_page()
            await demo_page.goto(demo_url)
            panel_page = await context.new_page()
            await panel_page.goto(f"chrome-extension://{extension_id}/panel.html")
            await expect(
                panel_page.get_by_role("heading", name="Browser companion")
            ).to_be_visible()

            await panel_page.get_by_role("button", name="Connect runtime host").click()
            await expect(panel_page.get_by_role("button", name="Disconnect host")).to_be_visible(
                timeout=10_000
            )

            demo_tab_id = await worker.evaluate(
                """async (url) => {
                  const targets = await chrome.debugger.getTargets();
                  const target = targets.find(item => item.type === 'page' && item.url === url);
                  if (typeof target?.tabId !== 'number') throw new Error('demo tab was not found');
                  await chrome.tabs.update(target.tabId, { active: true });
                  return target.tabId;
                }""",
                demo_url,
            )
            await panel_page.get_by_role("button", name="Capture active tab").click()
            await expect(
                panel_page.get_by_role(
                    "heading", name=f"http://{urlsplit(demo_url).netloc}", exact=True
                )
            ).to_be_visible()
            await panel_page.get_by_role("button", name="Confirm and attach").click()

            attached_browser = await asyncio.wait_for(
                service.wait_for_attached_browser(wait_seconds=15),
                timeout=15,
            )
            assert attached_browser is not None
            assert service.runtime_session is not None
            assert service.runtime_session["status"] == "idle"
            snapshot = await asyncio.wait_for(attached_browser.observe(), timeout=15)
            assert snapshot.title == "BROWSKI local application demo"
            assert any(element.accessible_name == "Full name" for element in snapshot.elements)
            assert isinstance(demo_tab_id, int)
            attached_tab = panel_page.get_by_role(
                "region",
                name=f"http://{urlsplit(demo_url).netloc}",
                exact=True,
            )
            await expect(attached_tab).to_be_visible(timeout=10_000)
            await expect(attached_tab.get_by_text("attached", exact=True)).to_be_visible()

            try:
                yield AttachedHarness(
                    service, attached_browser, demo_page, panel_page, credentials, config_path
                )
            finally:
                await context.close()
    finally:
        await service.close()
        http_server.shutdown()
        http_server.server_close()
        http_thread.join(timeout=2)


async def test_native_sidepanel_creates_browser_owned_context(
    attached_harness: AttachedHarness,
) -> None:
    harness = attached_harness
    inspector = cast(CdpInspector, await harness.panel.context.new_cdp_session(harness.panel))
    try:
        # The real toolbar handler invokes this same Chrome API. A synthetic
        # user gesture here tests native placement separately from the panel
        # page's already-covered UI interactions.
        opened = await inspector.send(
            "Runtime.evaluate",
            {
                "expression": "(async () => { const window = await chrome.windows.getCurrent(); "
                "await chrome.sidePanel.open({windowId: window.id}); "
                "return true; })()",
                "userGesture": True,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        assert "exceptionDetails" not in opened, opened
        assert opened["result"] == {"type": "boolean", "value": True}
        await harness.panel.wait_for_function(
            "async () => (await chrome.runtime.getContexts("
            "{contextTypes: ['SIDE_PANEL']})).length > 0"
        )
    finally:
        await inspector.detach()


async def test_attached_typing_is_verified_and_detach_clears_session(
    attached_harness: AttachedHarness,
) -> None:
    harness = attached_harness
    snapshot = await harness.browser.observe()
    name_field = next(
        element for element in snapshot.elements if element.accessible_name == "Full name"
    )
    typed = await asyncio.wait_for(
        harness.browser.act(
            BrowserAction(
                type="type",
                target=ElementRef(
                    ref=name_field.ref,
                    id=name_field.id,
                    generation=snapshot.state_generation,
                ),
                text="Demo Applicant",
            )
        ),
        timeout=20,
    )
    assert "Ok" in typed["execution"], typed
    assert typed["verification"]["status"] == "SUCCESS", typed
    await expect(harness.demo.get_by_label("Full name")).to_have_value("Demo Applicant")

    await harness.panel.get_by_role("button", name="Detach tab").click()
    await expect(harness.panel.get_by_role("button", name="Detach tab")).not_to_be_visible()
    await expect(harness.panel.get_by_role("button", name="Confirm and attach")).to_be_visible()
    await asyncio.wait_for(_wait_for_detached(harness.service), timeout=10)


async def test_attached_viewport_capture_returns_transient_bounded_png(
    attached_harness: AttachedHarness,
) -> None:
    harness = attached_harness
    tab_id = await harness.browser.active_tab_id()
    assert tab_id is not None
    screenshot = await harness.browser.capture_viewport_screenshot(tab_id)
    assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")
    assert 0 < len(screenshot) <= 4 * 1024 * 1024
    assert (await harness.browser.observe()).active_tab == tab_id


async def test_panel_settings_roundtrip_keeps_synthetic_key_out_of_browser_storage(
    attached_harness: AttachedHarness,
) -> None:
    harness = attached_harness
    await harness.panel.get_by_text("Settings and transport details", exact=True).click()
    effort = harness.panel.get_by_label("Default reasoning effort")
    await expect(effort).to_be_enabled()
    await effort.select_option("none")
    await harness.panel.get_by_role("button", name="Save runtime settings").click()
    await expect(harness.panel.get_by_role("button", name="Save runtime settings")).to_be_disabled()
    assert 'effort = "none"' in harness.config_path.read_text()
    assert harness.config_path.stat().st_mode & 0o077 == 0

    synthetic_key = "sk-fixture-only-never-valid-browski-secret-6821"
    key_input = harness.panel.get_by_label("Configure key on this device")
    await key_input.fill(synthetic_key)
    await harness.panel.get_by_role("button", name="Save securely").click()
    await expect(key_input).to_have_value("")
    await expect(harness.panel.get_by_role("button", name="Remove key")).to_be_visible()
    assert harness.credentials.value == synthetic_key
    worker = await _extension_worker(harness.panel.context)
    stored = await worker.evaluate(
        "async () => ({local: await chrome.storage.local.get(null), "
        "session: await chrome.storage.session.get(null)})"
    )
    assert synthetic_key not in str(stored)
    assert synthetic_key not in await harness.demo.content()
    assert synthetic_key not in await harness.panel.locator("main").inner_text()
    assert synthetic_key not in harness.config_path.read_text()
    await harness.panel.get_by_role("button", name="Remove key").click()
    await expect(harness.panel.get_by_role("button", name="Remove key")).not_to_be_visible()
    assert harness.credentials.value is None


async def test_owned_tabs_use_one_engine_and_reject_unowned_targets(
    attached_harness: AttachedHarness,
) -> None:
    harness = attached_harness
    original = await harness.browser.observe()
    assert original.active_tab is not None
    created = await harness.browser.act(
        BrowserAction(type="new_tab", url=harness.demo.url + "guide.html")
    )
    assert "Ok" in created["execution"], created
    assert created["verification"]["status"] == "SUCCESS", created
    tabs = await harness.browser.tabs()
    guide = next(tab for tab in tabs if tab.id != original.active_tab)
    assert guide.id.startswith("browser-tab-")
    assert (await harness.browser.observe()).active_tab == original.active_tab

    switched = await harness.browser.act(BrowserAction(type="activate_tab", tab=guide.id))
    assert switched["verification"]["status"] == "SUCCESS", switched
    observed_guide = await harness.browser.observe()
    assert observed_guide.active_tab == guide.id
    assert "Internship reference guide" in (observed_guide.title or "")
    assert any("BROWSKI-DEMO-42" in (element.text or "") for element in observed_guide.elements)

    refused = await harness.browser.act(BrowserAction(type="activate_tab", tab="not-owned"))
    assert "Err" in refused["execution"], refused
    assert (await harness.browser.observe()).active_tab == guide.id
    returned = await harness.browser.act(
        BrowserAction(type="activate_tab", tab=original.active_tab)
    )
    assert returned["verification"]["status"] == "SUCCESS", returned
    initial_close = await harness.browser.act(
        BrowserAction(type="close_tab", tab=original.active_tab)
    )
    assert "Err" in initial_close["execution"], initial_close
    assert not harness.demo.is_closed()
    assert (await harness.browser.observe()).active_tab == original.active_tab

    closed = await harness.browser.act(BrowserAction(type="close_tab", tab=guide.id))
    assert closed["verification"]["status"] == "SUCCESS", closed
    assert [tab.id for tab in await harness.browser.tabs()] == [original.active_tab]


def _use_scripted_reasoner(
    monkeypatch: pytest.MonkeyPatch,
    provider: ReasoningProvider,
) -> None:
    def create_provider(_config: BrowskiConfig) -> ReasoningProvider:
        return provider

    cli_module = import_module("browser_agent.cli.main")
    monkeypatch.setattr(cli_module, "create_luna_reasoning_provider", create_provider)


async def test_full_multistep_demo_preserves_grounded_memory_and_stops_before_submission(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = attached_harness
    provider = FullDemoReasoner()
    _use_scripted_reasoner(monkeypatch, provider)
    pause_received = asyncio.Event()
    original_pause = AgentRuntime.pause

    def record_pause(runtime: AgentRuntime, run_id: str) -> None:
        original_pause(runtime, run_id)
        pause_received.set()

    monkeypatch.setattr(AgentRuntime, "pause", record_pause)
    instruction = (
        'set "Full name" to "Alex Demo"; '
        'fill "Email address" with "alex@example.invalid"; '
        'type "Bengaluru" into "Preferred city"; '
        f'open "{harness.demo.url}guide.html" in a new tab; '
        'transfer "Reference code" from supporting page into "Supporting reference code". '
        "Return to the application and stop before final submission."
    )
    await harness.panel.get_by_label("Task instruction").fill(instruction)
    await harness.panel.get_by_role("button", name="Send task").click()
    await asyncio.wait_for(provider.deciding.wait(), timeout=15)
    await harness.panel.get_by_role("button", name="Pause", exact=True).click()
    await asyncio.wait_for(pause_received.wait(), timeout=10)
    provider.release.set()
    await expect(harness.panel.get_by_role("button", name="Resume", exact=True)).to_be_visible(
        timeout=15_000
    )
    await expect(harness.demo.get_by_label("Full name")).to_have_value("")
    await harness.panel.get_by_role("button", name="Resume", exact=True).click()
    try:
        await expect(harness.panel.get_by_text("Task completed", exact=True)).to_be_visible(
            timeout=90_000
        )
    except AssertionError as error:
        raise AssertionError(
            {
                "panel": await harness.panel.locator("main").inner_text(),
                "steps": [context.task.steps_taken for context in provider.contexts],
                "recovery_counts": [context.task.recovery_streak for context in provider.contexts],
            }
        ) from error
    await expect(harness.demo.get_by_label("Full name")).to_have_value("Alex Demo")
    await expect(harness.demo.get_by_label("Email address")).to_have_value("alex@example.invalid")
    await expect(harness.demo.get_by_label("Preferred city")).to_have_value("Bengaluru")
    await expect(harness.demo.get_by_label("Supporting reference code")).to_have_value(
        "BROWSKI-DEMO-42"
    )
    await expect(harness.demo.get_by_role("status")).to_have_text(
        "Application ready for review. Nothing has been submitted."
    )
    await expect(harness.panel.get_by_role("button", name="Approve action")).not_to_be_visible()
    assert len(await harness.browser.tabs()) == 2
    assert any(context.memory.authorized_transfer_evidence for context in provider.contexts)
    assert not any(context.observation.active_tab is None for context in provider.contexts)
    await expect(
        harness.panel.get_by_text("Verified browser result", exact=True).first
    ).to_be_visible()
    artifacts = Path("/tmp/browski-product-ui")
    await asyncio.to_thread(artifacts.mkdir, parents=True, exist_ok=True)
    for width in (440, 320):
        await harness.panel.set_viewport_size({"width": width, "height": 960})
        assert await harness.panel.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        await harness.panel.screenshot(path=str(artifacts / f"demo-panel-{width}.png"))


async def test_sidepanel_task_pauses_resumes_and_streams_verified_events(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = attached_harness
    provider = ScriptedReasoner(
        target_name="Continue to role details",
        evidence="2. Role details",
        blocked=True,
    )
    _use_scripted_reasoner(monkeypatch, provider)
    pause_received = asyncio.Event()
    original_pause = AgentRuntime.pause

    def record_pause(runtime: AgentRuntime, run_id: str) -> None:
        original_pause(runtime, run_id)
        pause_received.set()

    monkeypatch.setattr(AgentRuntime, "pause", record_pause)
    await harness.panel.get_by_label("Task instruction").fill("Continue to role details.")
    await harness.panel.get_by_role("button", name="Send task").click()
    await asyncio.wait_for(provider.deciding.wait(), timeout=15)
    await harness.panel.get_by_role("button", name="Pause", exact=True).click()
    await asyncio.wait_for(pause_received.wait(), timeout=10)
    provider.release.set()
    await expect(harness.panel.get_by_role("button", name="Resume", exact=True)).to_be_visible(
        timeout=15_000
    )
    await expect(harness.demo.get_by_role("heading", name="1. Contact details")).to_be_visible()
    await harness.panel.get_by_role("button", name="Resume", exact=True).click()
    try:
        await expect(harness.demo.get_by_role("heading", name="2. Role details")).to_be_visible(
            timeout=20_000
        )
    except AssertionError as error:
        # All task/page values here are synthetic local fixture data.
        raise AssertionError(await harness.panel.locator("main").inner_text()) from error
    await expect(harness.panel.get_by_text("Task completed", exact=True)).to_be_visible(
        timeout=20_000
    )
    await expect(harness.panel.get_by_text("Verified browser result", exact=True)).to_be_visible()


async def test_sidepanel_stop_cancels_decision_without_clicking(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = attached_harness
    provider = ScriptedReasoner(
        target_name="Continue to role details",
        evidence="2. Role details",
        blocked=True,
    )
    _use_scripted_reasoner(monkeypatch, provider)
    await harness.panel.get_by_label("Task instruction").fill("Continue to role details.")
    await harness.panel.get_by_role("button", name="Send task").click()
    await asyncio.wait_for(provider.deciding.wait(), timeout=15)
    await harness.panel.get_by_role("button", name="Stop", exact=True).click()
    await asyncio.wait_for(provider.cancelled.wait(), timeout=10)
    await expect(harness.panel.get_by_text("Task stopped", exact=True)).to_be_visible(
        timeout=15_000
    )
    await asyncio.wait_for(_wait_for_detached(harness.service), timeout=10)
    await expect(
        harness.panel.get_by_role("button", name="Detach tab", exact=True)
    ).not_to_be_visible()
    assert not harness.demo.is_closed(), "stopping the task must leave the Chrome tab open"
    await expect(harness.demo.get_by_role("heading", name="1. Contact details")).to_be_visible()


@pytest.mark.parametrize("disconnect", ["tab_closed", "host_disconnected"])
async def test_owned_session_loss_cancels_pending_decision(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
    disconnect: str,
) -> None:
    harness = attached_harness
    provider = ScriptedReasoner(
        target_name="Continue to role details",
        evidence="2. Role details",
        blocked=True,
    )
    _use_scripted_reasoner(monkeypatch, provider)
    await harness.panel.get_by_label("Task instruction").fill("Continue to role details.")
    await harness.panel.get_by_role("button", name="Send task").click()
    await asyncio.wait_for(provider.deciding.wait(), timeout=15)
    if disconnect == "tab_closed":
        await harness.demo.close()
    else:
        await harness.panel.get_by_role("button", name="Disconnect host").click()
    await asyncio.wait_for(provider.cancelled.wait(), timeout=15)
    await asyncio.wait_for(_wait_for_detached(harness.service), timeout=15)
    await expect(harness.panel.get_by_role("button", name="Detach tab")).not_to_be_visible()


@pytest.mark.parametrize("pause_before_confirmation", [False, True])
async def test_sidepanel_high_risk_denial_prevents_submission(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
    pause_before_confirmation: bool,
) -> None:
    harness = attached_harness
    # A manual page interaction is setup, not an agent action.
    await harness.demo.get_by_role("button", name="Continue to role details").click()
    # This test isolates approval semantics; keep its submit target in view.
    # Scrolling behavior has separate executor coverage.
    submit_button = harness.demo.get_by_role("button", name="Submit application")
    await submit_button.scroll_into_view_if_needed()
    await expect(submit_button).to_be_in_viewport()
    setup_snapshot = await harness.browser.observe()
    submit_element = next(
        element
        for element in setup_snapshot.elements
        if element.accessible_name == "Submit application"
    )
    diagnostics = {
        "element": submit_element.model_dump(),
        "scroll": setup_snapshot.scroll,
        "viewport": setup_snapshot.viewport,
        "browser_geometry": await submit_button.evaluate(
            "element => ({rect: element.getBoundingClientRect().toJSON(), "
            "scroll: window.scrollY, width: innerWidth, height: innerHeight})"
        ),
    }
    if not submit_element.interactable:
        raise AssertionError(diagnostics)
    provider = ScriptedReasoner(
        target_name="Submit application",
        evidence="Submission is disabled in this demo",
        blocked=pause_before_confirmation,
    )
    _use_scripted_reasoner(monkeypatch, provider)
    pause_received = asyncio.Event()
    original_pause = AgentRuntime.pause

    def record_pause(runtime: AgentRuntime, run_id: str) -> None:
        original_pause(runtime, run_id)
        pause_received.set()

    monkeypatch.setattr(AgentRuntime, "pause", record_pause)
    await harness.panel.get_by_label("Task instruction").fill("Submit the demo application.")
    await harness.panel.get_by_role("button", name="Send task").click()
    if pause_before_confirmation:
        await asyncio.wait_for(provider.deciding.wait(), timeout=15)
        await harness.panel.get_by_role("button", name="Pause", exact=True).click()
        await asyncio.wait_for(pause_received.wait(), timeout=10)
        provider.release.set()
        try:
            await expect(
                harness.panel.get_by_role("button", name="Resume", exact=True)
            ).to_be_visible(timeout=15_000)
        except AssertionError as error:
            latest = provider.contexts[-1]
            raise AssertionError(
                {
                    "candidate_options": latest.candidate_options,
                    "target": [
                        element.model_dump()
                        for element in latest.observation.elements
                        if element.name == provider.target_name
                    ],
                }
            ) from error
        await harness.panel.get_by_role("button", name="Resume", exact=True).click()
    try:
        await expect(harness.panel.get_by_role("button", name="Deny action")).to_be_visible(
            timeout=15_000
        )
    except AssertionError as error:
        latest = provider.contexts[-1]
        raise AssertionError(
            {
                "candidate_options": latest.candidate_options,
                "target": [
                    element.model_dump()
                    for element in latest.observation.elements
                    if element.name == provider.target_name
                ],
                "panel": await harness.panel.locator("main").inner_text(),
                "fresh_target": [
                    element.model_dump()
                    for element in (await harness.browser.observe()).elements
                    if element.accessible_name == provider.target_name
                ],
                "browser_geometry": await submit_button.evaluate(
                    "element => { const rect = element.getBoundingClientRect(); "
                    "const top = document.elementFromPoint(rect.x + rect.width / 2, "
                    "rect.y + rect.height / 2); return {rect: rect.toJSON(), "
                    "scroll: scrollY, width: innerWidth, height: innerHeight, "
                    "hit: top === element || element.contains(top)}; }"
                ),
            }
        ) from error
    await expect(harness.demo.get_by_role("status")).not_to_contain_text("Submission is disabled")
    await harness.panel.get_by_role("button", name="Deny action").click()
    await expect(harness.panel.get_by_role("button", name="Deny action")).not_to_be_visible(
        timeout=15_000
    )
    await expect(
        harness.panel.get_by_text("Task stopped without completion", exact=True)
    ).to_be_visible(timeout=15_000)
    await expect(harness.demo.get_by_role("status")).not_to_contain_text("Submission is disabled")


async def test_sidepanel_explicit_approval_executes_only_the_pending_local_action(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = attached_harness
    await harness.demo.get_by_role("button", name="Continue to role details").click()
    await harness.demo.get_by_role("button", name="Submit application").scroll_into_view_if_needed()
    provider = ScriptedReasoner(
        target_name="Submit application",
        evidence="Submission is disabled in this demo",
    )
    _use_scripted_reasoner(monkeypatch, provider)
    await harness.panel.get_by_label("Task instruction").fill("Submit the local demo application.")
    await harness.panel.get_by_role("button", name="Send task").click()
    approve = harness.panel.get_by_role("button", name="Approve action")
    await expect(approve).to_be_visible(timeout=20_000)
    await expect(harness.demo.get_by_role("status")).not_to_contain_text("Submission is disabled")
    await approve.click()
    await expect(harness.demo.get_by_role("status")).to_have_text(
        "Submission is disabled in this demo. No data was sent.", timeout=20_000
    )
    await expect(harness.panel.get_by_text("Task completed", exact=True)).to_be_visible(
        timeout=20_000
    )
    await expect(approve).not_to_be_visible()
