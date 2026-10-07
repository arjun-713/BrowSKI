"""Typed decision provider configuration and construction."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from browser_agent.decisions.adaptive import AdaptiveDecisionProvider
from browser_agent.decisions.base import DecisionProvider
from browser_agent.decisions.calibration import ProviderCalibration
from browser_agent.decisions.jev import JevProvider
from browser_agent.decisions.laya import LayaProvider


class DecisionProviderName(StrEnum):
    LAYA = "laya"
    JEV = "jev"
    ADAPTIVE = "adaptive"


class DecisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: DecisionProviderName = DecisionProviderName.LAYA
    laya_endpoint: str = "http://127.0.0.1:8000"
    laya_timeout_ms: int = Field(default=5_000, gt=0)
    laya_health_timeout_ms: int = Field(default=1_000, gt=0)
    jev_timeout_ms: int = Field(default=10_000, gt=0)
    fallback_to_jev: bool = True
    calibration: ProviderCalibration = Field(default_factory=ProviderCalibration)


def create_decision_provider(
    config: DecisionConfig,
    *,
    laya_model: Any | None = None,
    jev_client: Any | None = None,
) -> DecisionProvider:
    if config.provider == DecisionProviderName.LAYA:
        return LayaProvider(
            model=laya_model,
            endpoint_url=config.laya_endpoint,
            timeout_ms=config.laya_timeout_ms,
            health_timeout_ms=config.laya_health_timeout_ms,
            calibration=config.calibration.laya,
            calibration_id=config.calibration.laya.calibration_id,
        )
    if config.provider == DecisionProviderName.JEV:
        return JevProvider(
            client=jev_client,
            timeout_ms=config.jev_timeout_ms,
            calibration=config.calibration.jev,
            calibration_id=config.calibration.jev.calibration_id,
        )
    laya = LayaProvider(
        model=laya_model,
        endpoint_url=config.laya_endpoint,
        timeout_ms=config.laya_timeout_ms,
        health_timeout_ms=config.laya_health_timeout_ms,
        calibration=config.calibration.laya,
        calibration_id=config.calibration.laya.calibration_id,
    )
    jev = JevProvider(
        client=jev_client,
        timeout_ms=config.jev_timeout_ms,
        calibration=config.calibration.jev,
        calibration_id=config.calibration.jev.calibration_id,
    )
    return AdaptiveDecisionProvider(laya, jev, fallback_to_jev=config.fallback_to_jev)
