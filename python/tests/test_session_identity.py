"""Browser-session identity access must not enter the native lock synchronously."""

from __future__ import annotations

import pytest

import browser_agent
from browser_agent import BrowserSession


@pytest.mark.asyncio
async def test_session_id_property_uses_setup_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNativeSession:
        def __init__(self) -> None:
            self.session_id_calls = 0

        def session_id(self) -> str:
            self.session_id_calls += 1
            return "cached-native-session"

        def close(self) -> None:
            return None

    class FakePyBrowserSession:
        @staticmethod
        def launch(
            _headless: bool,
            _browser_code_enabled: bool,
        ) -> FakeNativeSession:
            return native

    class FakeNativeModule:
        PyBrowserSession = FakePyBrowserSession

    native = FakeNativeSession()
    monkeypatch.setattr(browser_agent, "_core", FakeNativeModule, raising=False)

    async with BrowserSession.launch() as session:
        assert native.session_id_calls == 1
        assert session.session_id == "cached-native-session"
        assert session.session_id == "cached-native-session"
        assert native.session_id_calls == 1

    assert session.session_id is None
