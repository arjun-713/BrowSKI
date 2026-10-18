"""Real Fast field/workflow regressions, separate from product and provider unit tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

from browser_agent.engines.contracts import CompletionCriteria


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome literal fields"
)
@pytest.mark.parametrize(
    "provider_name",
    ["fixture", "laya", "mutating-fixture", "mask-fixture", "duplicate-fixture", "missing-fixture"],
)
async def test_fast_requires_actual_field_values_before_matching_page_can_complete(
    article_site: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_name: str
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

    if provider_name == "laya" and os.environ.get("BROWSKI_LAYA_E2E") != "1":
        pytest.skip("Prepared local CPU Laya required")
    (tmp_path / "fields.html").write_text(
        '<h1>Draft form</h1><label>Name<input name="name"></label>'
        '<label>City<input name="city"></label>'
    )
    if provider_name == "mask-fixture":
        path = tmp_path / "fields.html"
        path.write_text(
            path.read_text().replace(
                '<input name="name">',
                '<input name="name" oninput="this.value=this.value.toUpperCase()">',
            )
        )
    if provider_name in {"duplicate-fixture", "missing-fixture"}:
        path = tmp_path / "fields.html"
        html = path.read_text()
        if provider_name == "duplicate-fixture":
            html += '<label>Name<input name="other-name"></label>'
        else:
            html = html.replace('<label>City<input name="city"></label>', "")
        path.write_text(html)
    owned = FastBrowser()

    def browser_factory(**kwargs: Any) -> FastBrowser:
        return owned

    monkeypatch.setattr(fast, "FastBrowser", browser_factory)
    observations: list[dict[str, str]] = []
    approvals: list[str] = []

    async def approve(request: ActionApproval) -> bool:
        assert request.action == "input"
        assert request.target in {"Name", "City"}
        approvals.append(request.target)
        return True

    async def events(event: EngineEvent) -> None:
        if event.kind == "verification":
            assert owned.browser is not None
            page = cast(Any, await owned.browser.get_current_page())
            raw = await page.evaluate(
                "() => JSON.stringify(Object.fromEntries(Array.from("
                "document.querySelectorAll('input')).map(e=>[e.name,e.value])))"
            )
            observations.append(json.loads(raw))

    class FieldFixture:
        name = "fixture"
        model = "bounded-field-fixture"
        calls = 0

        async def predict(self, request: FastRequest) -> FastDecision:
            self.calls += 1
            if provider_name == "mutating-fixture" and self.calls > 1:
                return FastDecision(
                    observation_id=request.observation.id,
                    provider=self.name,
                    model=self.model,
                    operation=Operation.BLOCKED,
                    latency_ms=0,
                )
            field = next(
                c for c in request.observation.candidates if c.operation is Operation.TYPE_TEXT
            )
            if provider_name == "mutating-fixture":
                assert owned.browser is not None
                page = cast(Any, await owned.browser.get_current_page())
                await page.evaluate("() => document.querySelector('input').value='Someone else'")
            return FastDecision(
                observation_id=request.observation.id,
                provider=self.name,
                model=self.model,
                operation=Operation.TYPE_TEXT,
                candidate_id=field.id,
                latency_ms=0,
            )

        async def aclose(self) -> None:
            pass

    provider: FastDecisionProvider = (
        LayaFastProvider(Path(__file__).parents[2] / ".browser-data/laya-browser-v19s")
        if provider_name == "laya"
        else FieldFixture()
    )
    url = f"{article_site}/fields.html"
    result = await fast.run_fast(
        'Set "Name" to "Ada"; fill "City" with "Pune".',
        url,
        provider,
        criteria=CompletionCriteria(url=url, heading="Draft form"),
        event_sink=events,
        approve_action=approve,
    )
    print("BROWSKI_FIELD_METRIC " + json.dumps(result.model_dump(mode="json")))
    assert result.generative_calls == 0
    if provider_name in {"duplicate-fixture", "missing-fixture"}:
        assert not result.verified and result.action_count == 1
        assert result.status.value == "partially_completed"
        assert approvals == (["City"] if provider_name == "duplicate-fixture" else ["Name"])
    elif provider_name == "mask-fixture":
        assert not result.verified and result.action_count == 1
        assert result.failure_phase == "verification"
        assert approvals == ["Name"]
        assert observations[-1] == {"name": "ADA", "city": ""}
    elif provider_name == "mutating-fixture":
        assert not result.verified and result.action_count == 0
        assert result.recovery_count == 1
        assert approvals == []
    else:
        assert result.verified, result.model_dump()
        assert result.action_count == 2 and sorted(approvals) == ["City", "Name"]
        assert observations[-1] == {"name": "Ada", "city": "Pune"}


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real native browser controls"
)
@pytest.mark.parametrize(
    "case",
    [
        "fixture",
        "laya",
        "invalid-date",
        "date-range",
        "option-collision",
        "duplicate-labels",
        "duplicate-values",
        "label-attribute",
        "replaced-date",
        "replaced-date-wrong",
        "removed-date-after-selection",
        "disabled-option",
        "multiple-select",
        "stale-constraint",
        "delayed-options",
        "delayed-no-recovery",
    ],
)
async def test_native_date_and_option_workflow_checks_properties_and_events(
    article_site: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from browser_agent.engines import fast
    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.fast_browser import FastBrowser
    from browser_agent.engines.fast_contract import FastDecision, FastDecisionProvider, FastRequest
    from browser_agent.engines.fast_providers import LayaFastProvider
    from browser_agent.engines.lifecycle import ActionApproval

    if case == "laya" and os.environ.get("BROWSKI_LAYA_E2E") != "1":
        pytest.skip("Prepared CPU Laya required")
    (tmp_path / "native.html").write_text("""
        <h1>Native controls</h1>
        <label>Departure<input name="departure" type="date"
          min="2026-10-01" max="2026-12-31" required></label>
        <label>Color<select name="color" required><option value="">Choose</option>
        <option value="r">Red</option><option value="b">Blue</option></select></label>
        <script>window.changes={departure:0,color:0};
        document.querySelector('input').addEventListener('change',()=>changes.departure++);
        document.querySelector('select').addEventListener('change',()=>changes.color++);</script>
    """)
    path = tmp_path / "native.html"
    html = path.read_text()
    if case == "option-collision":
        html = html.replace('<option value="r">Red</option>', '<option value="Blue">Red</option>')
    elif case == "duplicate-labels":
        html = html.replace('<option value="r">Red</option>', '<option value="r">Blue</option>')
    elif case == "duplicate-values":
        html = html.replace('<option value="">Choose</option>', "")
        html = html.replace(
            '<option value="r">Red</option>', '<option value="same" selected>Red</option>'
        )
        html = html.replace('<option value="b">Blue</option>', '<option value="same">Blue</option>')
    elif case == "label-attribute":
        html = html.replace(
            '<option value="b">Blue</option>',
            '<option value="b" label="Blue">Internal option</option>',
        )
    elif case == "disabled-option":
        html = html.replace(
            '<option value="b">Blue</option>', '<option value="b" disabled>Blue</option>'
        )
    elif case == "multiple-select":
        html = html.replace(
            '<select name="color" required>', '<select name="color" multiple required>'
        )
    elif case in {"delayed-options", "delayed-no-recovery"}:
        html = html.replace('<option value="b">Blue</option>', "")
    if case in {"replaced-date", "replaced-date-wrong"}:
        html += """<script>document.querySelector('input').addEventListener('change', event => {
            const replacement = event.target.cloneNode(true);
            replacement.value = event.target.value;
            event.target.replaceWith(replacement);
        });</script>"""
        if case == "replaced-date-wrong":
            html = html.replace(
                "replacement.value = event.target.value;", "replacement.value = '2026-11-02';"
            )
    if case == "removed-date-after-selection":
        html += """<script>document.querySelector('select').addEventListener('change', () => {
            document.querySelector('input').remove();
        });</script>"""
    path.write_text(html)
    owned = FastBrowser()
    observed: list[dict[str, Any]] = []
    approvals: list[str] = []

    def browser_factory(**kwargs: Any) -> FastBrowser:
        return owned

    monkeypatch.setattr(fast, "FastBrowser", browser_factory)
    if case in {"delayed-options", "delayed-no-recovery"}:
        from browser_agent.engines import fast_browser

        original_state = fast_browser.native_field_state
        scheduled = False

        async def delayed_state(browser: Any, node: Any, proposed: str | None = None) -> Any:
            nonlocal scheduled
            state = await original_state(browser, node, proposed)
            if node.tag_name == "select" and not scheduled:
                scheduled = True
                page = await browser.get_current_page()
                await page.evaluate("""() => setTimeout(() => {
                    const option = document.createElement('option');
                    option.value = 'b'; option.text = 'Blue';
                    document.querySelector('select').append(option);
                }, 150)""")
            return state

        monkeypatch.setattr(fast_browser, "native_field_state", delayed_state)

    async def events(event: EngineEvent) -> None:
        if event.kind == "verification":
            assert owned.browser is not None
            page = cast(Any, await owned.browser.get_current_page())
            observed.append(
                json.loads(
                    await page.evaluate("""() => JSON.stringify({
                departure: document.querySelector('input')?.value ?? null,
                dateValid: document.querySelector('input')?.validity.valid ?? null,
                color: document.querySelector('select').value,
                label: document.querySelector('select').selectedOptions[0]?.label ?? "",
                selectValid: document.querySelector('select').validity.valid,
                changes: window.changes
            })""")
                )
            )

    async def approve(request: ActionApproval) -> bool:
        assert request.target in {"Departure", "Color"}
        assert request.action in {"input", "select option"}
        approvals.append(request.target)
        return True

    class NativeFixture:
        name = "fixture"
        model = "native-field-fixture"

        calls = 0

        async def predict(self, request: FastRequest) -> FastDecision:
            self.calls += 1
            target = request.observation.candidates[0]
            if case == "stale-constraint" and self.calls == 1:
                assert owned.browser is not None
                page = cast(Any, await owned.browser.get_current_page())
                await page.evaluate("() => document.querySelector('input').max='2026-10-31'")
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
        if case == "laya"
        else NativeFixture()
    )
    url = f"{article_site}/native.html"
    wanted_date = (
        "2026-02-30"
        if case == "invalid-date"
        else "2027-01-01"
        if case == "date-range"
        else "2026-11-03"
    )
    goal = (
        f'Set "Departure" to "{wanted_date}"; set "Color" to "Blue".'
        if case not in {"delayed-options", "delayed-no-recovery"}
        else 'Set "Color" to "Blue".'
    )
    result = await fast.run_fast(
        goal,
        url,
        provider,
        fast.FastConfig(max_recoveries=0 if case == "delayed-no-recovery" else 3),
        criteria=CompletionCriteria(url=url, heading="Native controls"),
        event_sink=events,
        approve_action=approve,
    )
    print("BROWSKI_NATIVE_METRIC " + json.dumps(result.model_dump(mode="json")))
    assert result.generative_calls == 0
    if case == "removed-date-after-selection":
        assert not result.verified and result.status.value == "partially_completed", (
            result.model_dump()
        )
        assert result.action_count == 2 and approvals == ["Departure", "Color"]
        assert observed[-1]["departure"] is None
        assert observed[-1]["changes"] == {"departure": 1, "color": 1}
    elif case == "replaced-date-wrong":
        assert not result.verified and result.action_count == 1
        assert result.failure_phase == "verification" and result.recovery_count == 1
        assert approvals == ["Departure"]
        assert observed[-1]["departure"] == "2026-11-02"
    elif case == "delayed-no-recovery":
        assert not result.verified and result.action_count == 0
        assert result.steps == 0 and approvals == []
    elif case == "invalid-date":
        assert not result.verified and result.action_count == 0
        assert result.failure_phase == "task" and approvals == []
    elif case in {
        "date-range",
        "duplicate-labels",
        "disabled-option",
        "multiple-select",
        "stale-constraint",
    }:
        assert not result.verified and result.status.value == "partially_completed", (
            result.model_dump()
        )
        assert result.action_count == 1
        if case in {"date-range", "stale-constraint"}:
            assert approvals == ["Color"] and observed[-1]["departure"] == ""
        else:
            assert approvals == ["Departure"] and observed[-1]["changes"]["color"] == 0
    elif case == "delayed-options":
        assert result.verified and result.action_count == 1, result.model_dump()
        assert result.recovery_count >= 1 and approvals == ["Color"]
        assert observed[-1]["color"] == "b" and observed[-1]["label"] == "Blue"
    else:
        assert result.verified and result.action_count == 2, result.model_dump()
        assert sorted(approvals) == ["Color", "Departure"]
        assert observed[-1] == {
            "departure": "2026-11-03",
            "dateValid": True,
            "color": "same" if case == "duplicate-values" else "b",
            "label": "Blue",
            "selectValid": True,
            "changes": {"departure": 1, "color": 1},
        }
