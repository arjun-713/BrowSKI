"""Task-owned Browser Use session and model-independent page evidence."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, Any, Self, cast

from browser_agent.engines.contracts import PageEvidence

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession


def is_http_url(value: object) -> bool:
    """Bound web navigation; local files, credentials and control characters are excluded."""
    from urllib.parse import urlsplit

    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return False
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        return bool(
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def configure_browser_use() -> None:
    """Disable optional outbound services before importing upstream modules."""
    for name in ("ANONYMIZED_TELEMETRY", "BROWSER_USE_CLOUD_SYNC", "BROWSER_USE_CLOUD_HINTS"):
        os.environ[name] = "false"
    os.environ["BROWSER_USE_SETUP_LOGGING"] = "false"
    os.environ["SKIP_LLM_API_KEY_VERIFICATION"] = "true"


async def page_evidence(browser: BrowserSession) -> PageEvidence | None:
    page = await browser.get_current_page()
    if page is None:
        return None
    raw = await cast(Any, page).evaluate(
        "() => JSON.stringify({url: location.href, title: document.title, "
        "headings: Array.from(document.querySelectorAll('h1'))."
        "filter(e => e.getClientRects().length > 0).map(e => e.innerText.trim())})"
    )
    return PageEvidence.model_validate_json(raw)


class ManagedBrowser:
    """One isolated profile; no reuse of personal browser cookies or user tabs."""

    def __init__(
        self, *, chrome_path: str = "/usr/bin/google-chrome", headless: bool = True
    ) -> None:
        self.chrome_path = chrome_path
        self.headless = headless
        self.workspace = tempfile.TemporaryDirectory(prefix="browski-engine-")
        self.browser: BrowserSession | None = None

    async def __aenter__(self) -> Self:
        configure_browser_use()
        try:
            from browser_use import Browser, BrowserProfile
        except ImportError as exc:
            self.workspace.cleanup()
            raise RuntimeError("Install browser-agent[engines] before starting an engine.") from exc
        profile = BrowserProfile(
            executable_path=self.chrome_path,
            user_data_dir=f"{self.workspace.name}/profile",
            downloads_path=f"{self.workspace.name}/downloads",
            headless=self.headless,
            use_cloud=False,
            keep_alive=True,
            enable_default_extensions=False,
        )
        self.browser = Browser(browser_profile=profile)
        return self

    async def __aexit__(self, *_: object) -> None:
        try:
            if self.browser is not None:
                import asyncio

                async with asyncio.timeout(20):
                    await self.browser.kill()
        finally:
            self.workspace.cleanup()
