"""Panel timeline: General shows one readable line per action; Fast keeps diagnostics."""

from __future__ import annotations

from browser_agent.engines.contracts import EngineEvent
from browser_agent.extension.engine_tasks import timeline_payload


def _payload(event: EngineEvent) -> dict[str, object] | None:
    return timeline_payload(event, session_id="s", run_id="r", sequence=1, request_id=None)


def _general(kind: str, **values: object) -> EngineEvent:
    return EngineEvent.model_validate(
        {"kind": kind, "engine": "general", "provider": "openai", **values}
    )


def test_general_actions_appear_once_with_their_public_goal() -> None:
    started = _payload(
        _general(
            "action_started",
            label="Clicked “Search”",
            detail="Search for the article",
            page_url="https://en.wikipedia.org/",
        )
    )
    assert started is not None
    assert started["label"] == "Clicked “Search”"
    assert started["detail"] == "Search for the article"
    assert started["pageUrl"] == "https://en.wikipedia.org/"
    assert _payload(_general("action_finished", label="Clicked “Search”", verified=None)) is None


def test_general_internal_diagnostics_stay_out_of_the_panel() -> None:
    for kind in ("inference_started", "inference_finished", "observation"):
        assert _payload(_general(kind)) is None


def test_general_failures_remain_visible() -> None:
    failed = _payload(_general("action_finished", label="Clicked “Buy”", verified=False))
    blocked = _payload(_general("approval_blocked", label="Action refused"))
    assert failed is not None and failed["label"] == "Clicked “Buy”"
    assert blocked is not None and blocked["status"] == "failed"


def test_fast_keeps_compact_provider_diagnostics() -> None:
    event = EngineEvent(kind="inference_finished", provider="laya", model="v19s", latency_ms=812)
    payload = _payload(event)
    assert payload is not None
    assert payload["detail"] == "fast / laya / v19s · 812 ms inference"


def test_terminal_timeline_detail_always_fits_the_extension_bound() -> None:
    # Regression: a long task summary in the final timeline line exceeded the
    # extension's 500-character detail bound, and the panel dropped the runtime.
    from browser_agent.extension.service import (
        _timeline_detail,  # pyright: ignore[reportPrivateUsage]
    )

    long_summary = "Price comparison incomplete. " * 60
    assert len(_timeline_detail({}, long_summary)) <= 500
    assert _timeline_detail({"reason": "The judge verified completion."}, long_summary) == (
        "The judge verified completion."
    )
    assert len(_timeline_detail({"reason": "x" * 900}, "")) <= 500
