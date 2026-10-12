"""Bounded, non-blocking shadow comparisons for the active Luna decision."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, cast

import structlog

from browser_agent.decisions.base import DecisionProvider, DecisionProviderTimeout
from browser_agent.telemetry.debug_log import record_debug
from browser_agent.telemetry.debug_sanitize import sanitize_debug_payload

_LOGGER = structlog.get_logger("browser_agent.agent.shadow")
_MAX_CANDIDATES = 16
_MAX_CHOICE_ID_LENGTH = 64
_SHADOW_INSTRUCTIONS = (
    "Choose one supplied candidate for shadow comparison only. "
    "Do not create or authorize an action."
)


@dataclass(frozen=True)
class ShadowComparisonEvent:
    """Safe comparison metadata without task text, candidate descriptions, or answers."""

    outcome: str
    run_id: str | None
    step: int | None
    elapsed_ms: float
    candidate_count: int
    laya_choice: str | None = None
    luna_choice: str | None = None
    agreement: bool | None = None
    raw_confidence: float | None = None
    answer_confidence: float | None = None
    normalized_confidence: float | None = None
    error_type: str | None = None


ShadowTelemetry = Callable[[ShadowComparisonEvent], None]


class ShadowDecisionManager:
    """Run at most one bounded Laya comparison without delaying Luna execution."""

    def __init__(
        self,
        provider: DecisionProvider,
        *,
        timeout_ms: int = 16_000,
        max_context_characters: int = 2_048,
        telemetry: ShadowTelemetry | None = None,
    ) -> None:
        if timeout_ms <= 0 or max_context_characters <= 0:
            raise ValueError("shadow bounds must be greater than zero")
        self._provider = provider
        self._timeout_seconds = timeout_ms / 1000
        self._max_context_characters = max_context_characters
        self._telemetry = telemetry
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False
        self._timed_out = False

    def schedule_choice(
        self,
        state: Mapping[str, Any],
        options: Mapping[str, str | None],
        luna_choice: str,
        *,
        run_id: str | None,
        step: int | None,
    ) -> bool:
        """Schedule a comparison and return immediately; skip if it would queue."""
        if self._closed or self._timed_out or self._tasks:
            outcome = "skipped_after_timeout" if self._timed_out else "skipped_busy"
            self._emit(
                ShadowComparisonEvent(
                    outcome=outcome,
                    run_id=_safe_run_id(run_id),
                    step=step,
                    elapsed_ms=0.0,
                    candidate_count=min(len(options), _MAX_CANDIDATES),
                )
            )
            return False
        if not 2 <= len(options) <= _MAX_CANDIDATES or any(
            len(key) > _MAX_CHOICE_ID_LENGTH for key in options
        ):
            self._emit(
                ShadowComparisonEvent(
                    outcome="skipped_invalid_candidates",
                    run_id=_safe_run_id(run_id),
                    step=step,
                    elapsed_ms=0.0,
                    candidate_count=len(options),
                )
            )
            return False

        try:
            safe_state, safe_options = self._bounded_request(state, options)
        except ValueError:
            self._emit(
                ShadowComparisonEvent(
                    outcome="skipped_context_limit",
                    run_id=_safe_run_id(run_id),
                    step=step,
                    elapsed_ms=0.0,
                    candidate_count=len(options),
                )
            )
            return False
        task = asyncio.create_task(
            self._compare(
                safe_state,
                safe_options,
                luna_choice,
                run_id=_safe_run_id(run_id),
                step=step,
            ),
            name="laya-shadow-comparison",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def close(self) -> None:
        """Cancel in-flight comparisons and wait for their coroutine cleanup."""
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _compare(
        self,
        state: Mapping[str, Any],
        options: Mapping[str, str | None],
        luna_choice: str,
        *,
        run_id: str | None,
        step: int | None,
    ) -> None:
        started = time.perf_counter()
        try:
            answer = await asyncio.wait_for(
                self._provider.choose(
                    state,
                    _SHADOW_INSTRUCTIONS,
                    options,
                ),
                timeout=self._timeout_seconds,
            )
        except (TimeoutError, DecisionProviderTimeout) as exc:
            # Laya's stdlib transport runs in a worker thread. Do not start more
            # work after cancelling its coroutine because that thread can finish
            # only when its own socket timeout expires.
            self._timed_out = True
            self._emit(
                ShadowComparisonEvent(
                    outcome="timeout",
                    run_id=run_id,
                    step=step,
                    elapsed_ms=_elapsed_ms(started),
                    candidate_count=len(options),
                    luna_choice=_valid_choice(luna_choice, options),
                    error_type=type(exc).__name__,
                )
            )
        except asyncio.CancelledError:
            self._emit(
                ShadowComparisonEvent(
                    outcome="cancelled",
                    run_id=run_id,
                    step=step,
                    elapsed_ms=_elapsed_ms(started),
                    candidate_count=len(options),
                )
            )
            raise
        except Exception as exc:
            self._emit(
                ShadowComparisonEvent(
                    outcome="error",
                    run_id=run_id,
                    step=step,
                    elapsed_ms=_elapsed_ms(started),
                    candidate_count=len(options),
                    luna_choice=_valid_choice(luna_choice, options),
                    error_type=type(exc).__name__,
                )
            )
        else:
            laya_choice = _valid_choice(answer.value, options)
            normalized_luna_choice = _valid_choice(luna_choice, options)
            raw_confidence = _confidence(answer.raw, "confidence")
            answer_confidence = _confidence(answer.raw, "answer_confidence")
            self._emit(
                ShadowComparisonEvent(
                    outcome="success" if laya_choice is not None else "invalid_choice",
                    run_id=run_id,
                    step=step,
                    elapsed_ms=_elapsed_ms(started),
                    candidate_count=len(options),
                    laya_choice=laya_choice,
                    luna_choice=normalized_luna_choice,
                    agreement=(laya_choice == normalized_luna_choice)
                    if laya_choice is not None and normalized_luna_choice is not None
                    else None,
                    raw_confidence=raw_confidence,
                    answer_confidence=answer_confidence,
                    normalized_confidence=answer.confidence_calibrated,
                )
            )

    def _bounded_request(
        self,
        state: Mapping[str, Any],
        options: Mapping[str, str | None],
    ) -> tuple[dict[str, Any], dict[str, str | None]]:
        """Keep only short task context and supplied choices; omit browser snapshots."""
        compact_state: dict[str, Any] = {}
        for key in ("task", "current_subgoal", "recent_outcome"):
            value = state.get(key)
            if isinstance(value, str) and value.strip():
                compact_state[key] = " ".join(value.split())[:256]

        safe_options = {str(key): _short_text(value, 96) for key, value in options.items()}
        payload = sanitize_debug_payload({"state": compact_state, "options": safe_options})
        raw_state = payload.get("state", {})
        raw_options = payload.get("options", {})
        if not isinstance(raw_state, dict) or not isinstance(raw_options, dict):
            return {}, safe_options

        state_values = cast(dict[object, object], raw_state)
        option_values = cast(dict[object, object], raw_options)
        clean_state: dict[str, object] = {str(key): value for key, value in state_values.items()}
        clean_options: dict[str, str | None] = {
            str(key): _optional_string(value) for key, value in option_values.items()
        }
        while _serialized_size(clean_state, clean_options) > self._max_context_characters:
            if clean_state:
                largest_key = max(clean_state, key=lambda key: len(str(clean_state[key])))
                current = str(clean_state[largest_key])
                clean_state[largest_key] = current[: max(0, len(current) // 2)]
                if not clean_state[largest_key]:
                    del clean_state[largest_key]
                continue
            largest_option = max(
                clean_options,
                key=lambda key: len(str(clean_options[key] or "")),
                default=None,
            )
            if largest_option is None:
                break
            current_option = clean_options[largest_option]
            if current_option is None or not current_option:
                break
            if len(current_option) <= 16:
                clean_options[largest_option] = ""
            else:
                clean_options[largest_option] = current_option[: len(current_option) // 2]

        if _serialized_size(clean_state, clean_options) > self._max_context_characters:
            raise ValueError("candidate identifiers exceed the shadow request bound")
        return clean_state, clean_options

    def _emit(self, event: ShadowComparisonEvent) -> None:
        _LOGGER.info(
            "laya_shadow_comparison",
            outcome=event.outcome,
            run_id=event.run_id,
            step=event.step,
            elapsed_ms=round(event.elapsed_ms, 3),
            candidate_count=event.candidate_count,
            laya_choice=event.laya_choice,
            luna_choice=event.luna_choice,
            agreement=event.agreement,
            raw_confidence=event.raw_confidence,
            answer_confidence=event.answer_confidence,
            normalized_confidence=event.normalized_confidence,
            error_type=event.error_type,
        )
        record_debug("agent.shadow_comparison", asdict(event), step=event.step)
        if self._telemetry is not None:
            try:
                self._telemetry(event)
            except Exception:
                _LOGGER.warning("laya_shadow_telemetry_failed")


def _safe_run_id(value: str | None) -> str | None:
    if not value:
        return None
    safe = "".join(char for char in value[:128] if char.isalnum() or char in "-_.:")
    return safe or None


def _valid_choice(value: object, options: Mapping[str, str | None]) -> str | None:
    if not isinstance(value, str) or len(value) > _MAX_CHOICE_ID_LENGTH:
        return None
    return value if value in options else None


def _short_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    return compact[:limit] or None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _confidence(value: Mapping[str, Any] | None, key: str) -> float | None:
    if value is None:
        return None
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    confidence = float(raw)
    if not isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return None
    return confidence


def _serialized_size(state: Mapping[str, Any], options: Mapping[str, str | None]) -> int:
    request = {
        "state": state,
        "questions": {
            "decision": {
                "type": "choice",
                "instructions": _SHADOW_INSTRUCTIONS,
                "criteria": options,
            }
        },
    }
    return len(json.dumps(request, ensure_ascii=True))


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
