"""Agent-facing contract for bounded semantic-data transforms."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BROWSER_CODE_SCRIPT_BYTES = 8_192
MAX_BROWSER_CODE_TIMEOUT_MS = 1_500
MAX_BROWSER_CODE_RESULT_BYTES = 16_384


class BrowserCodeProposal(BaseModel):
    """A pure transform request; it cannot mutate or control the live page."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    script: str = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)
    timeout_ms: int = Field(default=750, ge=1, le=MAX_BROWSER_CODE_TIMEOUT_MS)
    max_result_bytes: int = Field(
        default=MAX_BROWSER_CODE_RESULT_BYTES,
        ge=1,
        le=MAX_BROWSER_CODE_RESULT_BYTES,
    )

    @model_validator(mode="after")
    def validate_proposal(self) -> BrowserCodeProposal:
        if not self.script.strip():
            raise ValueError("script must not be blank")
        if len(self.script.encode("utf-8")) > MAX_BROWSER_CODE_SCRIPT_BYTES:
            raise ValueError("script exceeds the 8192-byte limit")
        if not self.purpose.strip():
            raise ValueError("purpose must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must explain why standard browser actions are insufficient")
        return self


class BrowserCodeRecord(BaseModel):
    """One bounded key/value datum from a transform result."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    key: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=500)


class BrowserCodePayload(BaseModel):
    """Fixed result schema accepted from the isolated engine."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    summary: str = Field(default="", max_length=1_000)
    records: list[BrowserCodeRecord] = Field(
        default_factory=lambda: list[BrowserCodeRecord](),
        max_length=32,
    )


class BrowserCodeResult(BaseModel):
    """Ephemeral result for one immediate Luna follow-up request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    state_generation: int = Field(ge=0)
    payload: BrowserCodePayload
