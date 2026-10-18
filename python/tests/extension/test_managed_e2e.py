"""Packaged BROWSKI 2.0 engine acceptance and frozen local navigation cases."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest
from playwright.async_api import expect

from .test_browser_e2e import (
    ProductHarness,
)
from .test_browser_e2e import (
    attached_harness as attached_harness,
)
from .test_browser_e2e import (
    pytestmark as pytestmark,
)


async def test_managed_general_task_runs_from_packaged_panel_and_verifies_page(
    attached_harness: ProductHarness,
    article_site: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Real UI/native bridge/Agent/Chrome; default inference is an offline HTTP fixture."""
    import json

    import httpx

    from browser_agent.engines import general, product
    from browser_agent.engines.general import GeneralConfig

    harness = attached_harness
    panel = harness.panel
    url = f"{article_site}/botany.html"
    live = os.environ.get("BROWSKI_GENERAL_LIVE_DEBUG") == "1"
    calls = 0

    def offline_model(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        action = (
            {"navigate": {"url": url, "new_tab": False}}
            if calls == 1
            else {"done": {"text": "The visible heading is Botany.", "success": True}}
        )
        return httpx.Response(
            200,
            json={
                "id": "offline-extension-fixture",
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

    official_run = general.run_general

    async def bounded_run(goal: str, config: GeneralConfig, **kwargs: Any) -> Any:
        config = config.model_copy(update={"headless": True, "max_calls": 2, "max_steps": 3})
        if not live:
            kwargs["model_transport"] = httpx.MockTransport(offline_model)
        return await official_run(goal, config, **kwargs)

    monkeypatch.setattr(general, "run_general", bounded_run)
    if not live:
        monkeypatch.setattr(product, "configured_openai_api_key", lambda: "offline-fixture-only")
    await panel.get_by_label("Engine", exact=True).select_option("general")
    await expect(panel.get_by_text("Opens a separate task browser.", exact=False)).to_be_visible()
    await panel.locator(".settings-section > summary").click()
    await panel.get_by_label("Generative text", exact=True).select_option("openai")
    await panel.get_by_label("Permit paid API calls for tasks").check()
    await panel.get_by_role("button", name="Save runtime settings", exact=True).click()
    await expect(
        panel.get_by_role("button", name="Save runtime settings", exact=True)
    ).to_be_disabled()
    await panel.locator(".settings-section > summary").click()
    await panel.set_viewport_size({"width": 380, "height": 860})
    await panel.locator(".task-outcome-fields > summary").click()
    await panel.get_by_label("Starting page", exact=True).fill(url)
    await panel.get_by_label("Expected final page URL").fill(url)
    await panel.get_by_label("Expected page heading").fill("Botany")
    await panel.get_by_label("Task instruction").fill(
        f"Open {url} and report its visible main heading."
    )
    await panel.get_by_role("button", name="Send task", exact=True).click()
    await expect(panel.get_by_role("heading", name="Task completed", exact=True)).to_be_visible(
        timeout=90_000
    )
    assert harness.service.runtime_session is not None
    assert harness.service.runtime_session["status"] == "completed"
    assert harness.service.runtime_session["engine"] == "general"
    # Managed execution must not decorate or navigate the source tab.
    assert await harness.demo.title() == "BROWSKI local application demo"
    assert not await harness.demo.locator("#browski-activity-indicator").count()
    await panel.screenshot(path=str(tmp_path / "managed-result.png"), full_page=True)
    assert await panel.evaluate("document.documentElement.scrollWidth <= innerWidth")
    print(
        json.dumps(
            {
                "engine": "general",
                "live_model": live,
                "offline_calls": calls,
                "screenshot": str(tmp_path / "managed-result.png"),
            }
        )
    )
    if not live:
        assert calls == 2


@pytest.mark.skipif(os.environ.get("BROWSKI_LAYA_E2E") != "1", reason="prepared CPU Laya required")
async def test_managed_laya_multistep_task_from_panel_uses_no_hosted_inference(
    attached_harness: ProductHarness,
    article_site: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from browser_agent.engines import product

    def deny_hosted_credentials() -> None:
        raise AssertionError("Local task must not access OpenAI credentials")

    monkeypatch.setattr(product, "configured_openai_api_key", deny_hosted_credentials)
    panel = attached_harness.panel
    await panel.get_by_label("Engine", exact=True).select_option("fast")
    await panel.locator(".settings-section > summary").click()
    checkpoint = Path(__file__).parents[3] / ".browser-data/laya-browser-v19s"
    await panel.get_by_label("Local Laya checkpoint").fill(str(checkpoint))
    await panel.get_by_label("Permit paid API calls for tasks").uncheck()
    await panel.get_by_role("button", name="Save runtime settings", exact=True).click()
    await expect(
        panel.get_by_role("button", name="Save runtime settings", exact=True)
    ).to_be_disabled()
    await panel.locator(".settings-section > summary").click()
    await panel.locator(".task-outcome-fields > summary").click()
    await panel.get_by_label("Starting page", exact=True).fill(f"{article_site}/index.html")
    await panel.get_by_label("Expected final page URL").fill(f"{article_site}/leaf.html")
    await panel.get_by_label("Expected page heading").fill("Leaf structure")
    await panel.get_by_label("Task instruction").fill(
        "Open Botany, then open its Leaf structure article."
    )
    await panel.get_by_role("button", name="Send task", exact=True).click()
    await expect(panel.get_by_role("heading", name="Task completed", exact=True)).to_be_visible(
        timeout=120_000
    )
    assert attached_harness.service.runtime_session is not None
    assert attached_harness.service.runtime_session["provider"] == "laya"
    await expect(panel.get_by_text("No paid inference.", exact=False)).to_be_visible()


def _first_look_cases() -> list[dict[str, Any]]:
    root = Path(__file__).parents[3]
    data = json.loads((root / "benchmarks/synthetic/v2-navigation-first-look.json").read_text())
    return cast(list[dict[str, Any]], data["cases"])


@pytest.mark.skipif(
    os.environ.get("BROWSKI_V2_HOLDOUT_E2E") != "1",
    reason="explicit first-look CPU Laya evaluation; no paid inference",
)
@pytest.mark.parametrize("case", _first_look_cases(), ids=lambda case: case["id"])
async def test_frozen_navigation_first_look_from_packaged_panel(
    attached_harness: ProductHarness,
    article_site: str,
    tmp_path: Path,
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import html

    from browser_agent.engines import product
    from browser_agent.engines.contracts import EngineResult

    for relative, page in case["pages"].items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        links = " ".join(
            f'<a href="{html.escape(link["href"], quote=True)}">{html.escape(link["label"])}</a>'
            for link in page["links"]
        )
        path.write_text(
            f"<title>{html.escape(page['heading'])}</title><h1>{html.escape(page['heading'])}</h1>{links}"
        )
    done = asyncio.Event()
    results: list[EngineResult] = []
    original = product.execute_managed_task

    async def measured(*args: Any, **kwargs: Any) -> EngineResult:
        result = await original(*args, **kwargs)
        results.append(result)
        done.set()
        return result

    monkeypatch.setattr(product, "execute_managed_task", measured)
    panel = attached_harness.panel
    await panel.get_by_label("Engine", exact=True).select_option("fast")
    await panel.locator(".settings-section > summary").click()
    await panel.get_by_label("Local Laya checkpoint").fill(
        str(Path(__file__).parents[3] / ".browser-data/laya-browser-v19s")
    )
    await panel.get_by_label("Permit paid API calls for tasks").uncheck()
    await panel.get_by_role("button", name="Save runtime settings", exact=True).click()
    await expect(
        panel.get_by_role("button", name="Save runtime settings", exact=True)
    ).to_be_disabled()
    await panel.locator(".settings-section > summary").click()
    await panel.locator(".task-outcome-fields > summary").click()
    await panel.get_by_label("Starting page", exact=True).fill(f"{article_site}/{case['start']}")
    await panel.get_by_label("Expected final page URL").fill(f"{article_site}/{case['final']}")
    await panel.get_by_label("Expected page heading").fill(case["heading"])
    await panel.get_by_label("Task instruction").fill(case["goal"])
    await panel.get_by_role("button", name="Send task", exact=True).click()
    await asyncio.wait_for(done.wait(), 150)
    result = results[0]
    record = {
        "suite": "v2-navigation-first-look-2026-10-18",
        "case": case["id"],
        **result.model_dump(mode="json"),
    }
    print("BROWSKI_METRIC " + json.dumps(record))
    assert result.generative_calls == 0
    assert result.verified, record
    assert result.action_count >= case["min_actions"]
    await expect(panel.get_by_role("heading", name="Task completed", exact=True)).to_be_visible()


@pytest.mark.skipif(os.environ.get("BROWSKI_LAYA_E2E") != "1", reason="prepared CPU Laya required")
@pytest.mark.parametrize("attached_harness", ["fast"], indirect=True)
@pytest.mark.parametrize("task_kind", ["navigation", "fields", "native", "submit"])
async def test_fresh_default_runs_local_task_without_legacy_attachment(
    attached_harness: ProductHarness,
    article_site: str,
    monkeypatch: pytest.MonkeyPatch,
    task_kind: str,
    tmp_path: Path,
) -> None:
    from browser_agent.engines import product

    def no_hosted_credentials() -> None:
        raise AssertionError("Local default must not access hosted credentials")

    monkeypatch.setattr(product, "configured_openai_api_key", no_hosted_credentials)
    panel = attached_harness.panel
    await expect(panel.get_by_label("Engine", exact=True)).to_have_value("fast")
    assert await panel.get_by_role("button", name="Capture active tab").count() == 0
    await panel.locator(".task-outcome-fields > summary").click()
    if task_kind == "fields":
        (tmp_path / "fields.html").write_text(
            '<h1>Draft form</h1><label>Name<input name="name"></label>'
            '<label>City<input name="city"></label>'
        )
    elif task_kind == "native":
        (tmp_path / "native.html").write_text("""
            <h1>Native controls</h1>
            <label>Departure<input type="date" name="departure"
              min="2026-10-01" max="2026-12-31" required></label>
            <label>Color<select name="color" required><option value="">Choose</option>
            <option value="r">Red</option><option value="b">Blue</option></select></label>
        """)
    elif task_kind == "submit":
        (tmp_path / "submit.html").write_text("""
            <h1>Draft form</h1><form action="/receipt.html" method="get">
            <label>Name<input name="name" required></label>
            <label>City<input name="city" required></label>
            <button type="submit">Save demo record</button></form>
        """)
        (tmp_path / "receipt.html").write_text("<h1>Saved local draft</h1>")
    scenarios = {
        "navigation": (
            "botany.html",
            "Botany",
            f"Open the Botany article from {article_site}/index.html",
        ),
        "fields": (
            "fields.html",
            "Draft form",
            f'Open {article_site}/fields.html; set "Name" to "Ada"; fill "City" with "Pune".',
        ),
        "native": (
            "native.html",
            "Native controls",
            f"Open {article_site}/native.html; "
            'set "Departure" to "2026-11-03"; set "Color" to "Blue".',
        ),
        "submit": (
            "receipt.html?name=Ada&city=Pune",
            "Saved local draft",
            f'Open {article_site}/submit.html; set "Name" to "Ada"; '
            'fill "City" with "Pune"; click "Save demo record".',
        ),
    }
    path, heading, goal = scenarios[task_kind]
    await panel.get_by_label("Expected final page URL").fill(f"{article_site}/{path}")
    await panel.get_by_label("Expected page heading").fill(heading)
    # Exercise the normal task-link start path instead of the debug starting-page field.
    await panel.get_by_label("Task instruction").fill(goal)
    await panel.get_by_role("button", name="Send task", exact=True).click()
    if task_kind in {"fields", "native", "submit"}:
        seen: set[str] = set()
        expected_approvals = 3 if task_kind == "submit" else 2
        for _ in range(expected_approvals):

            async def next_approval() -> dict[str, object]:
                while True:
                    pending = attached_harness.service._pending_approval  # pyright: ignore[reportPrivateUsage]
                    if pending is not None and pending["approvalId"] not in seen:
                        return pending
                    await asyncio.sleep(0.05)

            pending = await asyncio.wait_for(next_approval(), 60)
            seen.add(str(pending["approvalId"]))
            await expect(panel.get_by_text(str(pending["summary"]), exact=True)).to_be_visible()
            await panel.get_by_role("button", name="Approve action", exact=True).click()
        assert len(seen) == expected_approvals
    await expect(panel.get_by_role("heading", name="Task completed", exact=True)).to_be_visible(
        timeout=120_000
    )
    assert attached_harness.service.runtime_session is not None
    assert attached_harness.service.runtime_session["browserMode"] == "managed"
    assert attached_harness.service._browser_session is None  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("attached_harness", ["fast"], indirect=True)
@pytest.mark.parametrize("response", ["approve", "deny", "stop", "changed"])
async def test_managed_general_form_approval_from_packaged_panel(
    attached_harness: ProductHarness,
    article_site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    """Real Agent and UI approval; scripted inference proves plumbing, not model accuracy."""
    import httpx

    from browser_agent.engines import general, product
    from browser_agent.engines.browser_use_runtime import ManagedBrowser
    from browser_agent.engines.contracts import EngineResult
    from browser_agent.engines.general import GeneralConfig

    (tmp_path / "form.html").write_text("""
        <h1>Local draft</h1><label>Name<input name="name" id="name"></label>
        <button id="save" onclick="if(document.querySelector('input').value==='Ada'){
          history.replaceState({},'', '/receipt.html?name=Ada');
          document.body.innerHTML='<h1>Saved demo record</h1>'}">Save demo record</button>
    """)
    harness = attached_harness
    owned: list[ManagedBrowser] = []
    results: list[EngineResult] = []
    calls = 0
    original_run = general.run_general

    def managed_browser(**kwargs: Any) -> ManagedBrowser:
        instance = ManagedBrowser(**kwargs)
        owned.append(instance)
        return instance

    async def offline_model(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        browser = owned[0].browser
        assert browser is not None
        if calls == 1:
            action = {"navigate": {"url": f"{article_site}/form.html", "new_tab": False}}
        elif calls in {2, 3}:
            state = await browser.get_browser_state_summary(include_screenshot=False, cached=True)
            target = "name" if calls == 2 else "save"
            index = next(
                i
                for i, node in state.dom_state.selector_map.items()
                if node.attributes.get("id") == target
            )
            action = (
                {"input": {"index": index, "text": "Ada", "clear": True}}
                if calls == 2
                else {"click": {"index": index}}
            )
        else:
            action = {"done": {"text": "Saved demo record", "success": True}}
        return httpx.Response(
            200,
            json={
                "id": "offline-local-form",
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

    async def bounded_run(goal: str, config: GeneralConfig, **kwargs: Any) -> EngineResult:
        result = await original_run(
            goal,
            config.model_copy(update={"max_calls": 4, "max_steps": 5}),
            model_transport=httpx.MockTransport(offline_model),
            **kwargs,
        )
        results.append(result)
        return result

    monkeypatch.setattr(general, "ManagedBrowser", managed_browser)
    monkeypatch.setattr(general, "run_general", bounded_run)
    monkeypatch.setattr(product, "configured_openai_api_key", lambda: "offline-fixture-only")
    panel = harness.panel
    await panel.get_by_label("Engine", exact=True).select_option("general")
    await panel.locator(".settings-section > summary").click()
    await panel.get_by_label("Generative text", exact=True).select_option("openai")
    await panel.get_by_label("Permit paid API calls for tasks").check()
    await panel.get_by_role("button", name="Save runtime settings", exact=True).click()
    await expect(
        panel.get_by_role("button", name="Save runtime settings", exact=True)
    ).to_be_disabled()
    await panel.locator(".settings-section > summary").click()
    await panel.locator(".task-outcome-fields > summary").click()
    await panel.get_by_label("Starting page", exact=True).fill(f"{article_site}/form.html")
    await panel.get_by_label("Expected final page URL").fill(
        f"{article_site}/receipt.html?name=Ada"
    )
    await panel.get_by_label("Expected page heading").fill("Saved demo record")
    await panel.get_by_label("Task instruction").fill(
        'Type "Ada" into Name and save the demo record.'
    )
    await panel.get_by_role("button", name="Send task", exact=True).click()
    await expect(panel.get_by_role("heading", name="Confirm input", exact=True)).to_be_visible(
        timeout=50_000
    )
    browser = owned[0].browser
    assert browser is not None
    page = cast(Any, await browser.get_current_page())
    assert await page.evaluate("() => document.querySelector('input').value") == ""
    await panel.get_by_role("button", name="Approve action", exact=True).click()
    await expect(panel.get_by_role("heading", name="Confirm click", exact=True)).to_be_visible(
        timeout=30_000
    )
    assert await page.evaluate("() => document.querySelector('input').value") == "Ada"
    assert "/receipt.html" not in await page.evaluate("() => location.href")
    if response == "changed":
        await page.evaluate("() => document.querySelector('input').value = 'Changed after review'")
    if response == "stop":
        await panel.get_by_role("button", name="Stop", exact=True).click()
    else:
        await panel.get_by_role(
            "button", name="Deny action" if response == "deny" else "Approve action", exact=True
        ).click()
    await expect(panel.get_by_role("heading", name="Confirm click", exact=True)).not_to_be_visible(
        timeout=30_000
    )
    for _ in range(100):
        if results:
            break
        await asyncio.sleep(0.1)
    assert results
    result = results[0]
    assert result.status.value == (
        "completed" if response == "approve" else "cancelled" if response == "stop" else "blocked"
    ), result.model_dump()
    assert result.verified is (response == "approve")
    assert result.action_count == (3 if response == "approve" else 2)
    assert calls == (4 if response == "approve" else 3)
    assert result.evidence is not None and (
        ("/receipt.html?name=Ada" in result.evidence.url) is (response == "approve")
    )
    assert harness.service.runtime_session is not None
    assert harness.service.runtime_session["status"] == result.status.value
    assert harness.service._browser_session is None  # pyright: ignore[reportPrivateUsage]
