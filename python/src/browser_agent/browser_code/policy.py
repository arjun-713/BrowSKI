"""Bounded policy for isolated transforms over Rust-owned semantic snapshots.

The policy requires an explicit capability and delegates execution to the
session-owned PyO3 helper. The helper builds the input projection in Rust and
does not expose page-realm code evaluation or browser APIs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError

MAX_SCRIPT_BYTES = 8_192
MAX_RESULT_BYTES = 16_384
MAX_TIMEOUT_MS = 1_500
MIN_TIMEOUT_MS = 1
MAX_PURPOSE_LENGTH = 160
MAX_REASON_LENGTH = 500


class BrowserCodeError(ValueError):
    """Base error for rejected or unavailable browser-code requests."""


class BrowserCodeDisabled(BrowserCodeError):
    """The capability is not enabled for this runtime."""


class BrowserCodeUnavailable(BrowserCodeError):
    """No safe browser-code executor is available."""


class BrowserCodeTimeout(BrowserCodeError):
    """The isolated transform exceeded its execution deadline."""


class BrowserCodeExecutionFailed(BrowserCodeError):
    """The isolated transform failed before producing a valid JSON result."""


class BrowserCodeValidationError(BrowserCodeError):
    """The request or returned payload violates the bounded contract."""


@dataclass(frozen=True, slots=True)
class BrowserCodeCapability:
    """Explicit capability switch; production default is disabled."""

    enabled: bool = False


@dataclass(frozen=True, slots=True)
class BrowserCodeTrace:
    """Safe trace metadata that omits source code and result content."""

    purpose_category: str
    reason_category: str
    script_sha256: str
    script_bytes: int
    timeout_ms: int
    max_result_bytes: int
    result_schema: str


@dataclass(frozen=True, slots=True)
class BrowserCodeRequest:
    """Validated request metadata; this object is not executable by itself."""

    script: str
    timeout_ms: int
    max_result_bytes: int
    result_schema: type[BaseModel]
    trace: BrowserCodeTrace


@dataclass(frozen=True, slots=True)
class BrowserCodeExecution:
    """Schema-checked result tied to the source snapshot generation."""

    state_generation: int
    result: BaseModel


class BrowserCodeExecutor(Protocol):
    """The narrow Rust binding surface; input data stays session-owned."""

    def transform_snapshot_json(
        self,
        script: str,
        timeout_ms: int = 750,
        max_result_bytes: int = MAX_RESULT_BYTES,
    ) -> str: ...


class BrowserCodePolicy:
    """Validate a transform request and its typed result at the Python boundary."""

    def __init__(self, capability: BrowserCodeCapability | None = None) -> None:
        self._capability = capability or BrowserCodeCapability()

    def prepare(
        self,
        *,
        script: str,
        purpose: str,
        reason: str,
        result_schema: object,
        timeout_ms: int = 750,
        max_result_bytes: int = MAX_RESULT_BYTES,
    ) -> BrowserCodeRequest:
        """Check capability and strict budgets before forming trace metadata."""
        if not self._capability.enabled:
            raise BrowserCodeDisabled("browser-code capability is disabled")
        if type(script) is not str or not script.strip():
            raise BrowserCodeValidationError("script must be a non-empty string")
        script_bytes = len(script.encode("utf-8"))
        if script_bytes > MAX_SCRIPT_BYTES:
            raise BrowserCodeValidationError("script exceeds the 8192-byte limit")
        if type(purpose) is not str or not purpose.strip() or len(purpose) > MAX_PURPOSE_LENGTH:
            raise BrowserCodeValidationError("purpose must be 1-160 non-blank characters")
        if type(reason) is not str or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
            raise BrowserCodeValidationError("reason must be 1-500 non-blank characters")
        if type(timeout_ms) is not int or not MIN_TIMEOUT_MS <= timeout_ms <= MAX_TIMEOUT_MS:
            raise BrowserCodeValidationError("timeout_ms must be an integer from 1 to 1500")
        if type(max_result_bytes) is not int or not 1 <= max_result_bytes <= MAX_RESULT_BYTES:
            raise BrowserCodeValidationError("max_result_bytes must be an integer from 1 to 16384")
        if not isinstance(result_schema, type) or not issubclass(result_schema, BaseModel):
            raise BrowserCodeValidationError("result_schema must be a Pydantic model class")
        validated_schema = result_schema

        trace = BrowserCodeTrace(
            purpose_category="semantic_data_transform",
            reason_category="explicit_capability_request",
            script_sha256=hashlib.sha256(script.encode("utf-8")).hexdigest(),
            script_bytes=script_bytes,
            timeout_ms=timeout_ms,
            max_result_bytes=max_result_bytes,
            result_schema=result_schema.__name__,
        )
        return BrowserCodeRequest(
            script=script,
            timeout_ms=timeout_ms,
            max_result_bytes=max_result_bytes,
            result_schema=validated_schema,
            trace=trace,
        )

    @staticmethod
    def validate_result(request: BrowserCodeRequest, payload: Any) -> BaseModel:
        """Apply the declared result schema and byte cap to executor output."""
        try:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise BrowserCodeValidationError("result is not JSON serializable") from exc
        if len(encoded.encode("utf-8")) > request.max_result_bytes:
            raise BrowserCodeValidationError("result exceeds the configured byte limit")
        try:
            return request.result_schema.model_validate_json(encoded)
        except ValidationError as exc:
            raise BrowserCodeValidationError("result does not match its declared schema") from exc

    @staticmethod
    def execute(
        request: BrowserCodeRequest,
        executor: BrowserCodeExecutor,
    ) -> BrowserCodeExecution:
        """Run a data-only transform through a session-owned Rust binding."""
        try:
            encoded = executor.transform_snapshot_json(
                request.script,
                timeout_ms=request.timeout_ms,
                max_result_bytes=request.max_result_bytes,
            )
        except PermissionError as exc:
            raise BrowserCodeDisabled("browser-code capability is disabled") from exc
        except TimeoutError as exc:
            raise BrowserCodeTimeout("browser-code execution timed out") from exc
        except Exception as exc:
            raise BrowserCodeExecutionFailed("isolated browser-code execution failed") from exc

        if type(encoded) is not str:
            raise BrowserCodeValidationError("executor response must be JSON text")
        if len(encoded.encode("utf-8")) > MAX_RESULT_BYTES + 256:
            raise BrowserCodeValidationError("executor response exceeds the byte limit")
        try:
            envelope = json.loads(encoded, parse_constant=_reject_json_constant)
        except (TypeError, ValueError) as exc:
            raise BrowserCodeValidationError(
                "isolated executor returned malformed JSON metadata"
            ) from exc
        if not isinstance(envelope, dict):
            raise BrowserCodeValidationError("executor response has an invalid shape")
        typed_envelope = cast(dict[str, object], envelope)
        if set(typed_envelope) != {
            "state_generation",
            "result_json",
        }:
            raise BrowserCodeValidationError("executor response has an invalid shape")
        generation = typed_envelope["state_generation"]
        result_json = typed_envelope["result_json"]
        if type(generation) is not int or generation < 0:
            raise BrowserCodeValidationError("executor generation is invalid")
        if type(result_json) is not str:
            raise BrowserCodeValidationError("executor result is not JSON text")
        if len(result_json.encode("utf-8")) > request.max_result_bytes:
            raise BrowserCodeValidationError("result exceeds the configured byte limit")
        try:
            payload = json.loads(result_json, parse_constant=_reject_json_constant)
        except (TypeError, ValueError) as exc:
            raise BrowserCodeValidationError("executor result is malformed JSON") from exc

        return BrowserCodeExecution(
            state_generation=generation,
            result=BrowserCodePolicy.validate_result(request, payload),
        )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")
