"""Shared product dispatch; explicit configuration selects one engine for a task."""

from __future__ import annotations

import os
from pathlib import Path

from browser_agent.cli.config import (
    BrowskiConfig,
    ExecutionEngine,
    FastProviderName,
    PrivacyMode,
    TextProviderName,
)
from browser_agent.credentials import configured_openai_api_key
from browser_agent.engines.contracts import CompletionCriteria, EngineResult, EventSink
from browser_agent.engines.fast_contract import FastDecisionProvider
from browser_agent.engines.lifecycle import TaskControl


class EngineConfigurationError(ValueError):
    """Safe actionable configuration failure before browser execution."""


async def execute_managed_task(
    goal: str,
    config: BrowskiConfig,
    *,
    start_url: str | None,
    criteria: CompletionCriteria | None,
    events: EventSink,
    control: TaskControl,
    headless: bool = False,
) -> EngineResult:
    options = config.agent
    if options.engine is ExecutionEngine.GENERAL:
        if options.text_provider is not TextProviderName.OPENAI or not options.allow_paid_api:
            raise EngineConfigurationError(
                "General needs generative inference. Explicitly select OpenAI text and permit "
                "paid API calls, or choose local Fast/Laya."
            )
        if config.privacy.mode is not PrivacyMode.STANDARD:
            raise EngineConfigurationError(
                "Hosted General inference is unavailable in this privacy mode."
            )
        from browser_agent.engines.general import GeneralConfig, run_general

        api_key = configured_openai_api_key()
        if not api_key:
            raise EngineConfigurationError(
                "OpenAI credentials are unavailable; choose local Fast/Laya or configure a key."
            )
        task = goal if not start_url else f"{goal}\nStarting page supplied by user: {start_url}"
        return await run_general(
            task,
            GeneralConfig(model=options.text_model, allow_paid_api=True, headless=headless),
            api_key=api_key,
            criteria=criteria,
            event_sink=events,
            cancel=control.cancel,
            before_decision=control.decision_boundary,
        )
    if options.engine is not ExecutionEngine.FAST:
        raise EngineConfigurationError("Managed dispatch supports General and Fast only.")
    if start_url is None:
        raise EngineConfigurationError(
            "Choose a starting page or include its HTTP(S) URL in the task."
        )
    from browser_agent.engines.fast import FastConfig, run_fast
    from browser_agent.engines.fast_providers import JevFastProvider, LayaFastProvider

    provider: FastDecisionProvider
    if options.fast_provider is FastProviderName.LAYA:
        from browser_agent.engines.laya_worker import validate_checkpoint

        checkpoint = Path(options.laya_checkpoint)
        try:
            validate_checkpoint(checkpoint)
        except ValueError as error:
            raise EngineConfigurationError(str(error)) from error
        provider = LayaFastProvider(checkpoint)
    else:
        if config.privacy.mode is not PrivacyMode.STANDARD:
            raise EngineConfigurationError(
                "Hosted Jev inference is unavailable in this privacy mode; use Laya."
            )
        try:
            provider = JevFastProvider(
                api_key=os.environ.get("TYPESAFE_API_KEY"),
                allow_paid_api=options.allow_paid_api,
                endpoint=options.jev_endpoint,
            )
        except ValueError as error:
            raise EngineConfigurationError(str(error)) from error
    return await run_fast(
        goal,
        start_url,
        provider,
        FastConfig(headless=headless),
        criteria=criteria,
        event_sink=events,
        cancel=control.cancel,
        before_decision=control.decision_boundary,
    )
