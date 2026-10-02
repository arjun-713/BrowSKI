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
    laya_model_id: str = "convaiinnovations/laya"
    laya_subfolder: str = "typed-decisions"
    calibration: ProviderCalibration = Field(default_factory=ProviderCalibration)


def create_decision_provider(
    config: DecisionConfig,
    *,
    laya_model: Any | None = None,
    jev_client: Any | None = None,
) -> DecisionProvider:
    laya = LayaProvider(
        model=laya_model,
        model_id=config.laya_model_id,
        subfolder=config.laya_subfolder,
        calibration=config.calibration.laya,
        calibration_id=config.calibration.laya.calibration_id,
    )
    jev = JevProvider(
        client=jev_client,
        calibration=config.calibration.jev,
        calibration_id=config.calibration.jev.calibration_id,
    )
    if config.provider == DecisionProviderName.LAYA:
        return laya
    if config.provider == DecisionProviderName.JEV:
        return jev
    return AdaptiveDecisionProvider(laya, jev)
