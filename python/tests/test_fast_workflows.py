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


@pytest.mark.skipif(
    os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome stagnation boundary"
)
@pytest.mark.parametrize(
    "unrelated_text_changes,decision_case",
    [(False, "click"), (True, "click"), (False, "wrong-operation"), (False, "abstained")],
)
async def test_fast_bounds_ineffective_clicks_and_rejects_invalid_operation_targets(
    article_site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unrelated_text_changes: bool,
    decision_case: str,
) -> None:
    from browser_agent.engines import fast
    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.fast_browser import FastBrowser
    from browser_agent.engines.fast_contract import FastDecision, FastRequest, Operation

    (tmp_path / "stalled.html").write_text("""
        <h1>Pending receipt</h1><output>0</output>
        <a href="/stalled.html" onclick="event.preventDefault(); window.attempts++;
          if (window.tick) document.querySelector('output').textContent=window.attempts;
        ">Open receipt</a><script>window.attempts=0;</script>
    """)
    owned = FastBrowser()
    attempts: list[int] = []
    progress: list[bool | None] = []

    def browser_factory(**kwargs: Any) -> FastBrowser:
        return owned

    monkeypatch.setattr(fast, "FastBrowser", browser_factory)

    async def events(event: EngineEvent) -> None:
        if event.kind not in {"task_started", "verification"}:
            return
        assert owned.browser is not None
        page = cast(Any, await owned.browser.get_current_page())
        if event.kind == "task_started":
            await page.evaluate(f"() => window.tick={json.dumps(unrelated_text_changes)}")
        if event.kind == "verification":
            attempts.append(int(await page.evaluate("() => window.attempts")))
            progress.append(event.verified)

    class RepeatingFixture:
        name = "fixture"
        model = "stagnation-fixture"

        async def predict(self, request: FastRequest) -> FastDecision:
            return FastDecision(
                observation_id=request.observation.id,
                provider=self.name,
                model=self.model,
                status="abstained" if decision_case == "abstained" else "selected",
                operation=Operation.TYPE_TEXT
                if decision_case == "wrong-operation"
                else Operation.CLICK,
                candidate_id=request.observation.candidates[0].id,
                latency_ms=0,
            )

        async def aclose(self) -> None:
            pass

    result = await fast.run_fast(
        "Open the receipt page.",
        f"{article_site}/stalled.html",
        RepeatingFixture(),
        fast.FastConfig(max_steps=5, max_recoveries=1),
        criteria=CompletionCriteria(url=f"{article_site}/receipt.html", heading="Receipt"),
        event_sink=events,
    )
    print("BROWSKI_STAGNATION_METRIC " + json.dumps(result.model_dump(mode="json")))
    assert not result.verified and result.generative_calls == 0
    if decision_case == "wrong-operation":
        assert result.action_count == 0 and result.provider_errors == 1, result.model_dump()
        assert result.failure_phase == "provider" and attempts == []
        return
    if decision_case == "abstained":
        assert result.action_count == 0 and result.provider_errors == 0
        assert result.error == "Decision provider abstained; no browser action executed."
        assert attempts == []
        return
    assert 1 <= result.action_count <= 2, result.model_dump()
    assert result.recovery_count == 2
    assert result.error == "Repeated unverified actions exhausted the recovery budget."
    assert attempts == list(range(1, result.action_count + 1))
    assert progress == [False] * result.action_count


@pytest.mark.skipif(os.environ.get("BROWSKI_ENGINE_E2E") != "1", reason="real Chrome form workflow")
@pytest.mark.parametrize(
    "case",
    [
        "fixture",
        "laya",
        "post",
        "deny",
        "changed",
        "changed-action",
        "noop",
        "wrong-receipt",
        "preexisting",
        "missing-criteria",
        "duplicate-button",
        "changed-on-submit",
    ],
)
async def test_fast_fills_approves_and_verifies_form_receipt(
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
    form = """<h1>Local draft</h1><form action="/receipt.html" method="get">
        <label>Name<input name="name" required></label>
        <label>City<input name="city" required></label>
        <button type="submit" onclick="sessionStorage.setItem('clicks',
          String(Number(sessionStorage.getItem('clicks') || 0) + 1))">Save demo record</button>
        </form>"""
    if case == "noop":
        form = form.replace('type="submit"', 'type="button"')
    elif case == "post":
        form = form.replace('action="/receipt.html" method="get"', 'action="/submit" method="post"')
    elif case == "wrong-receipt":
        form = form.replace("/receipt.html", "/wrong.html")
    elif case == "duplicate-button":
        form = form.replace("</form>", '<button type="button">Save demo record</button></form>')
    elif case == "changed-on-submit":
        form = form.replace(
            'method="get"', 'method="get" onsubmit="this.elements.name.value=\'Eve\'"'
        )
    (tmp_path / "submit.html").write_text(form)
    receipt = '<h1>Saved local draft</h1><output id="saved"></output><script>'
    receipt += "document.querySelector('output').textContent=location.search;</script>"
    (tmp_path / "receipt.html").write_text(receipt)
    (tmp_path / "wrong.html").write_text(receipt)
    owned = FastBrowser()
    approvals: list[str] = []
    receipts: list[str] = []
    clicks: list[int] = []

    def browser_factory(**kwargs: Any) -> FastBrowser:
        return owned

    monkeypatch.setattr(fast, "FastBrowser", browser_factory)

    async def approve(request: ActionApproval) -> bool:
        approvals.append(request.target)
        if request.action == "click":
            assert request.target == "Save demo record"
            assert owned.browser is not None
            page = cast(Any, await owned.browser.get_current_page())
            assert json.loads(
                await page.evaluate("""() => JSON.stringify(
                Object.fromEntries(new FormData(document.querySelector('form'))))""")
            ) == {"name": "Ada", "city": "Pune"}
            if case == "changed":
                await page.evaluate("() => document.querySelector('input').value='Changed'")
            if case == "changed-action":
                await page.evaluate("() => document.querySelector('form').action='/wrong.html'")
            return case != "deny"
        return True

    async def events(event: EngineEvent) -> None:
        if event.kind == "verification":
            assert owned.browser is not None
            page = cast(Any, await owned.browser.get_current_page())
            receipts.append(
                await page.evaluate("() => document.querySelector('#saved')?.textContent ?? ''")
            )
            clicks.append(int(await page.evaluate("() => sessionStorage.getItem('clicks') || '0'")))

    class FormFixture:
        name = "fixture"
        model = "form-workflow-fixture"

        async def predict(self, request: FastRequest) -> FastDecision:
            target = request.observation.candidates[0]
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
        else FormFixture()
    )
    result = await fast.run_fast(
        'Set "Name" to "Ada"; fill "City" with "Pune"; click "Save demo record".',
        f"{article_site}/submit.html",
        provider,
        criteria=(
            None
            if case == "missing-criteria"
            else CompletionCriteria(
                url=f"{article_site}/submit.html"
                if case == "preexisting"
                else f"{article_site}/receipt.html?name=Ada&city=Pune",
                heading="Local draft" if case == "preexisting" else "Saved local draft",
            )
        ),
        approve_action=approve,
        event_sink=events,
    )
    print("BROWSKI_SUBMIT_METRIC " + json.dumps(result.model_dump(mode="json")))
    assert result.generative_calls == 0
    if case in {"preexisting", "missing-criteria"}:
        assert not result.verified and result.action_count == 0
        assert result.failure_phase == "task" and approvals == []
        return
    if case == "duplicate-button":
        assert not result.verified and result.action_count == 2
        assert approvals == ["Name", "City"] and clicks[-1] == 0
        return
    assert sorted(approvals[:2]) == ["City", "Name"] and approvals[2:] == ["Save demo record"]
    if case in {"deny", "changed", "changed-action"}:
        assert not result.verified and result.action_count == 2
        assert result.failure_phase == "approval" and not any(receipts)
        assert clicks[-1] == 0
    elif case in {"noop", "wrong-receipt", "changed-on-submit"}:
        assert not result.verified and result.action_count == 3
        assert result.status.value == "partially_completed"
        assert clicks[-1] == 1
    else:
        assert result.verified and result.action_count == 3, result.model_dump()
        assert receipts[-1] == "?name=Ada&city=Pune" and clicks[-1] == 1
