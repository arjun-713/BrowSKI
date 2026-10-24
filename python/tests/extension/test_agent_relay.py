"""Relay contract: Browser Use's real connect sequence over a fake extension."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from typing import Any

import pytest

from browser_agent.extension.agent_relay import (
    AgentRelay,
    RelayError,
    session_method_allowed,
)

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("browser_use") is None, reason="engines extra not installed"
)


class FakeExtension:
    """Answers relay commands like the extension service worker would."""

    def __init__(self, *, fail: str | None = None) -> None:
        self.fail = fail
        self.commands: list[dict[str, Any]] = []
        self.closed_tabs: list[int] = []
        self.connection: Any = None
        self.task: asyncio.Task[None] | None = None
        self.next_tab = 200

    async def notify(self, kind: str, payload: dict[str, object]) -> None:
        if kind == "relay.open":
            self.task = asyncio.create_task(self._run(str(payload["url"])))

    async def _run(self, url: str) -> None:
        from websockets.asyncio.client import connect

        async with connect(url, max_size=None) as connection:
            self.connection = connection
            if self.fail:
                await connection.send(json.dumps({"type": "failed", "reason": self.fail}))
                return
            await connection.send(
                json.dumps(
                    {
                        "type": "ready",
                        "tabs": [{"tabId": 101, "url": "https://example.test/", "title": "Home"}],
                    }
                )
            )
            async for raw in connection:
                message = json.loads(raw)
                if message["type"] == "close":
                    return
                await connection.send(self._reply(message))

    def _reply(self, message: dict[str, Any]) -> str:
        """Successful results use the extension's raw frame: header line + body."""
        self.commands.append(message)
        result: dict[str, Any] = {}
        if message["type"] == "createTab":
            self.next_tab += 1
            result = {"tab": {"tabId": self.next_tab, "url": message["url"], "title": ""}}
        elif message["type"] == "closeTab":
            self.closed_tabs.append(message["tabId"])
        elif message.get("method") == "Runtime.evaluate":
            result = {"result": {"type": "number", "value": 2}}
        return f"R {json.dumps({'id': message['id']})}\n{json.dumps(result)}"

    async def send(self, message: dict[str, Any]) -> None:
        await self.connection.send(json.dumps(message))


@pytest.mark.asyncio
async def test_browser_use_connects_and_routes_commands_to_the_leased_tab() -> None:
    from browser_use import BrowserSession

    fake = FakeExtension()
    relay = AgentRelay(fake.notify)
    async with relay.lease() as lease:
        assert lease.cdp_url.startswith("ws://127.0.0.1:")
        session = BrowserSession(cdp_url=lease.cdp_url, keep_alive=True)
        await asyncio.wait_for(session.connect(), timeout=20)
        try:
            cdp = await session.get_or_create_cdp_session()
            value = await cdp.cdp_client.send.Runtime.evaluate(
                params={"expression": "1+1"}, session_id=cdp.session_id
            )
            assert value["result"].get("value") == 2
            forwarded = [c for c in fake.commands if c.get("method") == "Runtime.evaluate"]
            assert forwarded[-1]["tabId"] == 101
            assert forwarded[-1]["sessionId"] is None

            with pytest.raises(Exception, match="not available"):
                await cdp.cdp_client.send.Storage.getCookies(session_id=cdp.session_id)

            starting_target = cdp.target_id
            with pytest.raises(Exception, match="did not open"):
                await session.cdp_client.send.Target.closeTarget(
                    params={"targetId": starting_target}
                )

            created = await session.cdp_client.send.Target.createTarget(
                params={"url": "https://example.test/next"}
            )
            await session.cdp_client.send.Target.closeTarget(
                params={"targetId": created["targetId"]}
            )
            assert fake.closed_tabs == [201]
        finally:
            await session.stop()
    assert not relay.active
    assert fake.task is not None
    await asyncio.wait_for(fake.task, timeout=5)


@pytest.mark.asyncio
async def test_extension_failure_is_reported_before_the_agent_starts() -> None:
    fake = FakeExtension(fail="This tab cannot be controlled.")
    relay = AgentRelay(fake.notify)
    with pytest.raises(RelayError, match="cannot be controlled"):
        async with relay.lease():
            pass
    assert not relay.active


@pytest.mark.asyncio
async def test_user_cancel_from_the_browser_sets_the_lease_cancel_event() -> None:
    fake = FakeExtension()
    relay = AgentRelay(fake.notify)
    async with relay.lease() as lease:
        await fake.send({"type": "cancelled", "reason": "Debugging was cancelled in Chrome."})
        await asyncio.wait_for(lease.cancelled.wait(), timeout=5)
        assert lease.cancel_reason == "Debugging was cancelled in Chrome."


@pytest.mark.asyncio
async def test_only_one_lease_at_a_time() -> None:
    fake = FakeExtension()
    relay = AgentRelay(fake.notify)
    async with relay.lease():
        with pytest.raises(RelayError, match="already using"):
            async with relay.lease():
                pass


@pytest.mark.parametrize(
    ("method", "allowed"),
    [
        ("Runtime.evaluate", True),
        ("DOMSnapshot.captureSnapshot", True),
        ("Target.setAutoAttach", True),
        ("Network.enable", True),
        ("Network.getAllCookies", False),
        ("Storage.getCookies", False),
        ("Browser.close", False),
        ("Fetch.enable", False),
        ("Target.createTarget", False),
    ],
)
def test_session_policy(method: str, allowed: bool) -> None:
    assert session_method_allowed(method) is allowed
