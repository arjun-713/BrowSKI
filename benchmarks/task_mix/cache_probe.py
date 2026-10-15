"""Measure actual cache reads/writes on two bounded, non-executing Luna calls."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from browser_agent._types import (
    AgentObservation,
    PrunedElement,
    TaskState,
    WorkingMemory,
)
from browser_agent.credentials import (
    configured_openai_api_key,
    load_local_env_credentials,
)
from browser_agent.providers.privacy import ProviderBoundary
from browser_agent.reasoning import ReasoningContext, ReasoningEffort, ReasoningPurpose
from browser_agent.reasoning.openai_adapter import (
    DEFAULT_LUNA_MODEL,
    OpenAILunaProvider,
    ReasoningTelemetryEvent,
)
from browser_agent.telemetry.debug_log import DebugLogConfig, DebugRecorder


async def run_probe(output: Path, requests: int = 2, start_step: int = 1) -> None:
    load_local_env_credentials(Path(__file__).resolve().parents[2] / ".env")
    if not configured_openai_api_key():
        raise RuntimeError(
            "Configure an OpenAI key before running the opt-in cache probe"
        )
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    events: list[ReasoningTelemetryEvent] = []
    provider = ProviderBoundary(
        OpenAILunaProvider(api_key=configured_openai_api_key(), telemetry=events.append)
    )
    recorder = DebugRecorder(DebugLogConfig(enabled=True, directory=output / "debug"))
    try:
        with recorder.bind("cache-probe", "synthetic-cache-probe"):
            for index in range(start_step - 1, start_step - 1 + requests):
                task = f"Click the uniquely named Continue button for local step {index + 1}."
                context = ReasoningContext(
                    purpose=ReasoningPurpose.CHOOSE_ACTION,
                    task=TaskState(task=task, user_goal=task),
                    memory=WorkingMemory(user_goal=task),
                    observation=AgentObservation(
                        url="http://127.0.0.1/synthetic-cache-probe",
                        title=f"Local step {index + 1}",
                        state_generation=index + 1,
                        elements=[
                            PrunedElement(
                                ref="@continue", role="button", name="Continue"
                            )
                        ],
                    ),
                    candidate_options={
                        "c01": "click the Continue button at @continue",
                        "c02": "escalate because the bounded action is insufficient",
                    },
                )
                answer = await provider.reason(
                    context, model=DEFAULT_LUNA_MODEL, effort=ReasoningEffort.LOW
                )
                record = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "index": index,
                    "synthetic_context": context.model_dump(mode="json"),
                    "answer": answer.model_dump(mode="json"),
                    "usage_event": asdict(events[-1]),
                    "browser_actions_executed": 0,
                }
                with (output / "results.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
                event = events[-1]
                print(
                    f"call={index + 1} input={event.input_tokens} "
                    f"cached={event.cached_input_tokens} write={event.cache_write_tokens} "
                    f"output={event.output_tokens} latency_ms={event.elapsed_ms:.0f}",
                    flush=True,
                )
    finally:
        await provider.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requests", type=int, choices=(1, 2), default=2)
    parser.add_argument("--start-step", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    asyncio.run(run_probe(args.output, args.requests, args.start_step))


if __name__ == "__main__":
    main()
