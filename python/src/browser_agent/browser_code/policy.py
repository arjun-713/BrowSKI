"""Fail-closed policy surface for the M9 browser-code escape hatch.

The current Rust binding does not expose evaluation. Its internal evaluator
runs in the page realm, where code can mutate the page or use network APIs.
Until the Rust runtime provides an isolated, bounded read-only evaluator, this
module only validates requests and results; it never executes JavaScript.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

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


class BrowserCodeValidationError(BrowserCodeError):
    """The request or returned payload violates the bounded contract."""


@dataclass(frozen=True, slots=True)
class BrowserCodeCapability:
    """Explicit capability switch; production default is disabled."""

    enabled: bool = False


@dataclass(frozen=True, slots=True)
class BrowserCodeTrace:
    """Safe trace metadata that omits source code and result content."""

    purpose: str
    reason: str
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


class BrowserCodePolicy:
    """Validate bounded browser-code requests without providing execution."""

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
            purpose=purpose.strip(),
            reason=reason.strip(),
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
    def execute(_request: BrowserCodeRequest) -> None:
        """Fail closed until the Rust runtime offers a safe bounded evaluator."""
        raise BrowserCodeUnavailable(
            "browser-code execution is unavailable: Rust exposes no isolated, "
            "read-only page evaluator with enforceable timeout and network limits"
        )
