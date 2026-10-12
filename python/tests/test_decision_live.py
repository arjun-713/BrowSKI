"""Opt-in integration checks for explicitly configured System One providers."""

from __future__ import annotations

import os

import pytest

from browser_agent.decisions import (
    DecisionKind,
    DecisionQuestion,
    JevProvider,
    LayaProvider,
)


@pytest.mark.skipif(
    os.environ.get("BROWSKI_LIVE_LAYA") != "1",
    reason="set BROWSKI_LIVE_LAYA=1 to call the local Laya service",
)
async def test_live_laya_local_service_contract() -> None:
    provider = LayaProvider(
        endpoint_url=os.environ.get("BROWSKI_LAYA_ENDPOINT", "http://127.0.0.1:8001")
    )
    health = await provider.health_check()
    assert health.available, "local Laya service must be running before this opt-in test"
    result = await provider.evaluate(
        {"status": "The profile update confirmation is visible."},
        {"saved": DecisionQuestion(DecisionKind.NOUL, "Was the profile update saved?")},
    )
    assert result.provider == "laya"
    assert isinstance(result.answers["saved"].value, float)


@pytest.mark.skipif(
    os.environ.get("BROWSKI_LIVE_JEV") != "1",
    reason="set BROWSKI_LIVE_JEV=1 and configure the TypeSafe SDK credentials",
)
async def test_live_jev_typed_decision_contract() -> None:
    provider = JevProvider()
    result = await provider.evaluate(
        {"status": "The profile update confirmation is visible."},
        {"saved": DecisionQuestion(DecisionKind.NOUL, "Was the profile update saved?")},
    )
    assert result.provider == "jev"
    assert isinstance(result.answers["saved"].value, float)
    await provider.aclose()
