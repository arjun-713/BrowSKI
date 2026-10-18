"""BROWSKI 2.0 engine lifecycle and real-browser integration boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from browser_agent.engines.contracts import CompletionCriteria


async def test_general_rejects_paid_calls_before_import_or_key_access() -> None:
    from browser_agent.engines.general import GeneralConfig, run_general

    with pytest.raises(ValueError, match="opt-in"):
        await run_general("Open an article", GeneralConfig())
    with pytest.raises(ValueError, match="credentials"):
        await run_general("Open an article", GeneralConfig(allow_paid_api=True))


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1",
    reason="opt-in real Browser Use Chrome boundary; no model requests",
)
async def test_real_browser_use_navigation_has_independent_page_evidence(article_site: str) -> None:
    from browser_agent.engines.browser_use_runtime import ManagedBrowser, page_evidence

    async with ManagedBrowser() as owned:
        assert owned.browser is not None
        await owned.browser.start()
        page = await owned.browser.get_current_page()
        assert page is not None
        url = f"{article_site}/botany.html"
        await page.goto(url)
        evidence = await page_evidence(owned.browser)
        assert CompletionCriteria(url=url, heading="Botany").verify(evidence)


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1",
    reason="opt-in real Browser Use Agent with offline model responses",
)
@pytest.mark.parametrize("false_done", [False, True])
async def test_official_agent_executes_and_checks_real_browser_without_paid_inference(
    article_site: str,
    false_done: bool,
) -> None:
    from browser_agent.engines.general import GeneralConfig, run_general

    url = f"{article_site}/botany.html"
    calls: list[str] = []

    def offline_model(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        calls.append(str(request.url))
        action = (
            {"navigate": {"url": url, "new_tab": False}}
            if len(calls) == 1 and not false_done
            else {"done": {"text": "The heading is Botany.", "success": True}}
        )
        return httpx.Response(
            200,
            json={
                "id": "offline-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "offline-fixture",
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

    result = await run_general(
        f"Open {url} and report the heading.",
        GeneralConfig(allow_paid_api=True, max_calls=2),
        api_key="offline-fixture-only",
        criteria=CompletionCriteria(url=url, heading="Botany"),
        model_transport=httpx.MockTransport(offline_model),
    )
    assert result.verified is (not false_done), result.model_dump()
    assert result.generative_calls == (1 if false_done else 2)
    assert len(calls) == result.generative_calls
    if not false_done:
        assert result.evidence is not None and result.evidence.headings == ["Botany"]


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1",
    reason="real Browser Use cancellation while an offline inference request is pending",
)
async def test_cancellation_interrupts_an_inflight_model_request_without_paid_calls() -> None:
    import asyncio

    from browser_agent.engines.contracts import EngineStatus
    from browser_agent.engines.general import GeneralConfig, run_general

    entered = asyncio.Event()
    cancel = asyncio.Event()

    async def waiting_model(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Cancelled request unexpectedly resumed.")

    task = asyncio.create_task(
        run_general(
            "Read a page heading.",
            GeneralConfig(allow_paid_api=True),
            api_key="offline-fixture-only",
            cancel=cancel,
            model_transport=httpx.MockTransport(waiting_model),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=30)
        cancel.set()
        result = await asyncio.wait_for(task, timeout=30)
        assert result.status is EngineStatus.CANCELLED
        assert not result.verified
        assert result.generative_calls == 1
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.skipif(
    os.environ.get("BROWSKI_LAYA_E2E") != "1",
    reason="opt-in live CPU Laya task; requires prepared pinned checkpoint and engines extras",
)
@pytest.mark.parametrize(
    "goal,path,heading,min_actions",
    [
        ("Open the Botany article.", "botany.html", "Botany", 1),
        ("Open Botany, then open its Leaf structure article.", "leaf.html", "Leaf structure", 2),
    ],
)
async def test_live_laya_finishes_real_navigation_tasks(
    article_site: str, goal: str, path: str, heading: str, min_actions: int
) -> None:
    from browser_agent.engines.fast import run_fast
    from browser_agent.engines.fast_providers import LayaFastProvider

    root = Path(__file__).parents[2]
    provider = LayaFastProvider(root / ".browser-data/laya-browser-v19s")
    result = await run_fast(
        goal,
        f"{article_site}/index.html",
        provider,
        criteria=CompletionCriteria(url=f"{article_site}/{path}", heading=heading),
    )
    print(
        json.dumps(
            {
                "result": result.model_dump(mode="json"),
                "model_load_ms": provider.load_ms,
                "peak_rss_mib": provider.peak_rss_mib,
            }
        )
    )
    assert result.verified, result.model_dump()
    assert result.action_count >= min_actions
    assert result.generative_calls == 0
