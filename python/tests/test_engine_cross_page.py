"""Owned-tab and cross-page workflow regressions on the existing loopback fixture."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

from browser_agent.engines.contracts import CompletionCriteria


@pytest.mark.skipif(os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real source transfer")
@pytest.mark.parametrize("case", ["fixture", "laya", "field-only"])
async def test_transfer_uses_owned_source_and_actual_field_receipt(
    article_site: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from browser_agent.engines import fast
    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.fast_browser import FastBrowser
    from browser_agent.engines.fast_contract import (
        FastDecision,
        FastDecisionProvider,
        FastRequest,
        Operation,
    )
    from browser_agent.engines.fast_providers import LayaFastProvider
    from browser_agent.engines.lifecycle import ActionApproval

    if case == "laya" and os.environ.get("BROWSKI_LAYA_E2E") != "1":
        pytest.skip("Prepared CPU Laya required")
    (tmp_path / "transfer.html").write_text("""
        <title>Reference form</title><h1>Reference form</h1>
        <a href="/transfer-source.html" target="_blank">Reference</a>
        <form action="/transfer-receipt.html" method="get">
          <label>Reference code<input name="code" required></label>
          <button type="submit">Save reference</button>
        </form><script>window.writes=0;
        document.querySelector('input').addEventListener('change',()=>writes++);</script>
    """)
    (tmp_path / "transfer-source.html").write_text("""
        <title>Reference</title><h1>Reference</h1>
        <dl><dt>Reference code</dt><dd>REF-4821</dd></dl>
    """)
    (tmp_path / "transfer-receipt.html").write_text("<h1>Saved reference</h1>")
    owned = FastBrowser()
    approvals: list[str] = []
    visits: list[str] = []
    field_values: list[str] = []
    source_seen = False

    def factory(**kwargs: Any) -> FastBrowser:
        return owned

    monkeypatch.setattr(fast, "FastBrowser", factory)

    async def approve(request: ActionApproval) -> bool:
        approvals.append(request.target)
        return True

    async def events(event: EngineEvent) -> None:
        if event.kind in {"tab_selected", "verification"}:
            assert owned.browser is not None
            page = cast(Any, await owned.browser.get_current_page())
            visits.append(await page.evaluate("() => location.href"))
            value = await page.evaluate("() => document.querySelector('input')?.value ?? null")
            if value is not None:
                field_values.append(value)

    class TransferFixture:
        name = "fixture"
        model = "source-transfer-fixture"

        async def predict(self, request: FastRequest) -> FastDecision:
            nonlocal source_seen
            candidates = request.observation.candidates
            if request.observation.url.endswith("transfer-source.html"):
                source_seen = True
                selected = next(c for c in candidates if c.role == "tab")
            else:
                selected = next((c for c in candidates if c.operation is Operation.TYPE_TEXT), None)
                selected = selected or next(
                    (c for c in candidates if c.label == "Save reference"), None
                )
                if selected is None and not source_seen:
                    selected = next(c for c in candidates if c.label == "Reference")
            return FastDecision(
                observation_id=request.observation.id,
                provider=self.name,
                model=self.model,
                operation=selected.operation if selected is not None else Operation.BLOCKED,
                candidate_id=selected.id if selected is not None else None,
                latency_ms=0,
            )

        async def aclose(self) -> None:
            pass

    provider: FastDecisionProvider = (
        LayaFastProvider(Path(__file__).parents[2] / ".browser-data/laya-browser-v19s")
        if case == "laya"
        else TransferFixture()
    )
    goal = (
        'Open Reference in its supporting tab; transfer "Reference code" '
        'from supporting page into "Reference code"'
    )
    if case != "field-only":
        goal += '; click "Save reference".'
    result = await fast.run_fast(
        goal,
        f"{article_site}/transfer.html",
        provider,
        criteria=CompletionCriteria(
            url=f"{article_site}/transfer.html"
            if case == "field-only"
            else f"{article_site}/transfer-receipt.html?code=REF-4821",
            heading="Reference form" if case == "field-only" else "Saved reference",
        ),
        approve_action=approve,
        event_sink=events,
    )
    print("BROWSKI_TRANSFER_METRIC " + json.dumps(result.model_dump(mode="json")))
    assert result.verified, result.model_dump()
    assert result.action_count == (4 if case == "field-only" else 5)
    assert result.generative_calls == 0 and result.provider_errors == 0
    assert approvals == (
        ["Reference code"] if case == "field-only" else ["Reference code", "Save reference"]
    )
    assert f"{article_site}/transfer-source.html" in visits
    assert "REF-4821" in field_values


@pytest.mark.skipif(os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real owned Chrome tabs")
@pytest.mark.parametrize(
    "provider_name", ["fixture", "laya", "closed-fixture", "changed-fixture", "budget-fixture"]
)
async def test_fast_selects_supporting_tab_before_its_receipt(
    article_site: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_name: str
) -> None:
    from browser_agent.engines import fast
    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.fast_browser import FastBrowser
    from browser_agent.engines.fast_contract import FastDecision, FastDecisionProvider, FastRequest
    from browser_agent.engines.fast_providers import LayaFastProvider

    if provider_name == "laya" and os.environ.get("BROWSKI_LAYA_E2E") != "1":
        pytest.skip("Prepared CPU Laya required")
    (tmp_path / "tabs.html").write_text(
        "<title>Task start</title><h1>Task start</h1>"
        '<a href="/reference.html" target="_blank">Reference</a>'
    )
    (tmp_path / "reference.html").write_text(
        "<title>Reference</title><h1>Reference</h1>"
        '<p>Reference code: REF-4821</p><a href="/tab-receipt.html">Receipt</a>'
    )
    (tmp_path / "tab-receipt.html").write_text("<title>Receipt</title><h1>Reference receipt</h1>")
    owned = FastBrowser()
    visits: list[str] = []
    switches: list[str] = []
    target_counts: list[int] = []

    def browser_factory(**kwargs: Any) -> FastBrowser:
        return owned

    monkeypatch.setattr(fast, "FastBrowser", browser_factory)

    async def events(event: EngineEvent) -> None:
        if event.kind in {"verification", "tab_selected"}:
            assert owned.browser is not None
            page = cast(Any, await owned.browser.get_current_page())
            url = await page.evaluate("() => location.href")
            visits.append(url)
            target_counts.append(len(owned.browser.get_page_targets()))
            if event.kind == "tab_selected":
                assert event.verified is True
                switches.append(url)

    class TabsFixture:
        name = "fixture"
        model = "cross-page-fixture"
        invalidated = False

        async def predict(self, request: FastRequest) -> FastDecision:
            if self.invalidated:
                from browser_agent.engines.fast_contract import Operation

                return FastDecision(
                    observation_id=request.observation.id,
                    provider=self.name,
                    model=self.model,
                    operation=Operation.BLOCKED,
                    latency_ms=0,
                )
            target = request.observation.candidates[0]
            if target.role == "tab" and provider_name in {"closed-fixture", "changed-fixture"}:
                assert owned.browser is not None
                self.invalidated = True
                if provider_name == "closed-fixture":
                    await owned.browser.close_page(target.id[1:])
                else:
                    from browser_use.actor.page import Page

                    await cast(Any, Page(owned.browser, target.id[1:])).evaluate(
                        "() => history.replaceState({},'', '?revision=2')"
                    )
            return FastDecision(
                observation_id=request.observation.id,
                provider=self.name,
                model=self.model,
                operation=target.operation,
                candidate_id=target.id,
                latency_ms=0,
            )

        async def aclose(self) -> None:
            pass

    provider: FastDecisionProvider = (
        LayaFastProvider(Path(__file__).parents[2] / ".browser-data/laya-browser-v19s")
        if provider_name == "laya"
        else TabsFixture()
    )
    result = await fast.run_fast(
        "Open Reference in its supporting tab, then open that page's Receipt link.",
        f"{article_site}/tabs.html",
        provider,
        fast.FastConfig(max_steps=2 if provider_name == "budget-fixture" else 12),
        criteria=CompletionCriteria(
            url=f"{article_site}/tab-receipt.html", heading="Reference receipt"
        ),
        event_sink=events,
    )
    print("BROWSKI_TABS_METRIC " + json.dumps(result.model_dump(mode="json")))
    if provider_name == "budget-fixture":
        assert not result.verified and result.status.value == "partially_completed"
        assert 1 <= result.action_count <= 2 and len(switches) <= 1
        assert result.error == "Fast decision step budget exhausted."
        return
    if provider_name in {"closed-fixture", "changed-fixture"}:
        assert not result.verified and result.status.value == "partially_completed", (
            result.model_dump()
        )
        assert result.action_count == 1 and result.provider_errors == 0
        assert result.recovery_count >= 1 and switches == []
        assert f"{article_site}/reference.html" not in visits
        return
    assert result.verified, result.model_dump()
    assert result.generative_calls == 0 and result.action_count == 3
    assert switches == [f"{article_site}/reference.html"]
    assert f"{article_site}/reference.html" in visits
    assert max(target_counts) == 2


@pytest.mark.skipif(os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real owned Chrome tabs")
@pytest.mark.parametrize("case", ["same-url", "closed", "noop"])
async def test_focus_uses_full_target_identity_and_actual_browser_state(
    article_site: str, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from browser_agent.engines.browser_use_runtime import ManagedBrowser
    from browser_agent.engines.owned_tabs import (
        TabStateChanged,
        focus_owned_tab,
        observe_owned_tabs,
    )

    async with ManagedBrowser() as owned:
        assert owned.browser is not None
        browser = owned.browser
        await browser.start()
        first = await browser.get_current_page()
        assert first is not None
        url = f"{article_site}/botany.html"
        await first.goto(url)
        await browser.new_page(url)
        snapshot = None
        for _ in range(20):
            try:
                snapshot = await observe_owned_tabs(browser, {"127.0.0.1"})
            except TabStateChanged:
                await asyncio.sleep(0.05)
                continue
            if len(snapshot.tabs) == 2:
                break
            await asyncio.sleep(0.05)
        assert snapshot is not None and len(snapshot.tabs) == 2
        other = next(tab for tab in snapshot.tabs if tab.target_id != snapshot.active_id)
        assert other.evidence.url == url and len(other.target_id) > 4
        if case == "closed":
            await browser.close_page(other.target_id)
        elif case == "noop":
            from browser_use.browser.events import SwitchTabEvent

            original_dispatch = browser.event_bus.dispatch

            class NoFocusResult:
                def __await__(self) -> Any:
                    async def finished() -> None:
                        return None

                    return finished().__await__()

                async def event_result(self, **kwargs: Any) -> str:
                    return other.target_id

            def no_focus(event: Any, **kwargs: Any) -> Any:
                if isinstance(event, SwitchTabEvent):
                    return NoFocusResult()
                return original_dispatch(event, **kwargs)

            monkeypatch.setattr(browser.event_bus, "dispatch", no_focus)
        if case != "same-url":
            with pytest.raises(TabStateChanged):
                await focus_owned_tab(browser, other)
            current = browser.get_focused_target()
            assert current is not None and str(current.target_id) == snapshot.active_id
        else:
            await focus_owned_tab(browser, other)
            current = browser.get_focused_target()
            assert current is not None and str(current.target_id) == other.target_id


@pytest.mark.skipif(os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real General owned tabs")
@pytest.mark.parametrize("missing_target", [False, True])
async def test_general_switches_owned_tabs_with_offline_agent_responses(
    article_site: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_target: bool
) -> None:
    import httpx

    from browser_agent.engines import general
    from browser_agent.engines.browser_use_runtime import ManagedBrowser
    from browser_agent.engines.contracts import EngineEvent

    (tmp_path / "general-start.html").write_text("<h1>General start</h1>")
    (tmp_path / "general-source.html").write_text(
        "<h1>General source</h1><p>Reference code: REF-4821</p>"
    )
    owned = ManagedBrowser()
    visits: list[str] = []
    calls = 0

    def factory(**kwargs: Any) -> ManagedBrowser:
        return owned

    monkeypatch.setattr(general, "ManagedBrowser", factory)

    async def events(event: EngineEvent) -> None:
        if event.kind == "action_finished" and event.operation != "done":
            assert owned.browser is not None
            page = cast(Any, await owned.browser.get_current_page())
            visits.append(await page.evaluate("() => location.href"))

    async def model(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 2:
            path = "general-start.html" if calls == 1 else "general-source.html"
            action = {"navigate": {"url": f"{article_site}/{path}", "new_tab": calls == 2}}
        elif calls == 3:
            assert owned.browser is not None
            tab = next(
                t for t in await owned.browser.get_tabs() if t.url.endswith("general-start.html")
            )
            action = {"switch": {"tab_id": "zzzz" if missing_target else str(tab.target_id)[-4:]}}
        else:
            action = {"done": {"text": "General start; Reference code REF-4821", "success": True}}
        return httpx.Response(
            200,
            json={
                "id": "offline-tabs",
                "object": "chat.completion",
                "created": 1,
                "model": "offline",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"action": [action]}),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    result = await general.run_general(
        f"Open {article_site}/general-start.html, open the source in another tab, "
        "then return and report the start heading.",
        general.GeneralConfig(allow_paid_api=True, max_calls=4, max_steps=4),
        api_key="offline-fixture-only",
        model_transport=httpx.MockTransport(model),
        criteria=CompletionCriteria(
            url=f"{article_site}/general-start.html", heading="General start"
        ),
        event_sink=events,
    )
    if missing_target:
        # ADR-032: a refused switch no longer ends the run. The agent continues,
        # but it finishes on the source page, so the outcome stays unverified.
        assert not result.verified and result.action_count == 2
        assert result.failure_phase == "verification" and result.provider_errors == 0
        assert calls == 4
    else:
        assert result.verified and result.action_count == 3, result.model_dump()
        assert visits == [
            f"{article_site}/general-start.html",
            f"{article_site}/general-source.html",
            f"{article_site}/general-start.html",
        ]
        assert calls == 4
