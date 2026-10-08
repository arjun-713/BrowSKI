from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field

from browser_agent.browser_code import (
    BrowserCodeCapability,
    BrowserCodeDisabled,
    BrowserCodeExecution,
    BrowserCodeExecutionFailed,
    BrowserCodePolicy,
    BrowserCodeTimeout,
    BrowserCodeValidationError,
)


class PageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(max_length=100)
    links: list[str] = Field(max_length=4)


def enabled_policy() -> BrowserCodePolicy:
    return BrowserCodePolicy(BrowserCodeCapability(enabled=True))


def request(policy: BrowserCodePolicy, **overrides: object):
    values: dict[str, object] = {
        "script": "(snapshot) => ({title: snapshot.title, links: []})",
        "purpose": "extract page summary with potentially sensitive page text",
        "reason": "Contains page content that must not be retained in telemetry.",
        "result_schema": PageSummary,
    }
    values.update(overrides)
    return policy.prepare(**values)  # type: ignore[arg-type]


class FakeBrowserCodeExecutor:
    def __init__(self, payload: dict[str, object], generation: int = 12) -> None:
        self.payload = payload
        self.generation = generation

    def transform_snapshot_json(
        self,
        script: str,
        timeout_ms: int = 750,
        max_result_bytes: int = 16_384,
    ) -> str:
        import json

        assert script
        assert 1 <= timeout_ms <= 1_500
        assert 1 <= max_result_bytes <= 16_384
        return json.dumps(
            {
                "state_generation": self.generation,
                "result_json": json.dumps(self.payload, separators=(",", ":")),
            },
            separators=(",", ":"),
        )


def test_bounded_extraction_payload_validates_through_local_fake_seam() -> None:
    policy = enabled_policy()
    prepared = request(policy)

    execution = policy.execute(
        prepared,
        FakeBrowserCodeExecutor({"title": "Fixture page", "links": ["/help"]}),
    )

    assert isinstance(execution, BrowserCodeExecution)
    assert execution.state_generation == 12
    assert isinstance(execution.result, PageSummary)
    assert execution.result.title == "Fixture page"
    assert execution.result.links == ["/help"]
    assert prepared.trace.purpose_category == "semantic_data_transform"
    assert prepared.trace.reason_category == "explicit_capability_request"
    assert prepared.trace.script_sha256
    assert "document.title" not in repr(prepared.trace)
    assert "potentially sensitive" not in repr(prepared.trace)
    assert "page content" not in repr(prepared.trace)


def test_capability_is_disabled_by_default() -> None:
    with pytest.raises(BrowserCodeDisabled, match="disabled"):
        request(BrowserCodePolicy())


def test_oversized_script_is_rejected() -> None:
    with pytest.raises(BrowserCodeValidationError, match="8192-byte"):
        request(enabled_policy(), script="x" * 8_193)


def test_timeout_must_fit_hard_upper_bound() -> None:
    with pytest.raises(BrowserCodeValidationError, match="timeout_ms"):
        request(enabled_policy(), timeout_ms=1_501)


def test_malformed_result_is_rejected() -> None:
    prepared = request(enabled_policy())
    with pytest.raises(BrowserCodeValidationError, match="declared schema"):
        BrowserCodePolicy.validate_result(prepared, {"title": 7, "links": [], "extra": True})


def test_oversized_result_is_rejected_before_schema_validation() -> None:
    prepared = request(enabled_policy(), max_result_bytes=100)
    with pytest.raises(BrowserCodeValidationError, match="byte limit"):
        BrowserCodePolicy.validate_result(
            prepared,
            {"title": "x" * 100, "links": []},
        )


def test_executor_rejects_malformed_result_json() -> None:
    class MalformedExecutor:
        def transform_snapshot_json(
            self,
            script: str,
            timeout_ms: int = 750,
            max_result_bytes: int = 16_384,
        ) -> str:
            return '{"state_generation":12,"result_json":"not-json"}'

    with pytest.raises(BrowserCodeValidationError, match="malformed JSON"):
        BrowserCodePolicy.execute(request(enabled_policy()), MalformedExecutor())


def test_executor_rejects_invalid_generation_and_unexpected_fields() -> None:
    class InvalidExecutor:
        def transform_snapshot_json(
            self,
            script: str,
            timeout_ms: int = 750,
            max_result_bytes: int = 16_384,
        ) -> str:
            return '{"state_generation":true,"result_json":"{}","source":"must not be returned"}'

    with pytest.raises(BrowserCodeValidationError, match="invalid shape"):
        BrowserCodePolicy.execute(request(enabled_policy()), InvalidExecutor())


def test_executor_timeout_is_preserved_as_a_typed_failure() -> None:
    class TimedOutExecutor:
        def transform_snapshot_json(
            self,
            script: str,
            timeout_ms: int = 750,
            max_result_bytes: int = 16_384,
        ) -> str:
            raise TimeoutError("deadline")

    with pytest.raises(BrowserCodeTimeout, match="timed out"):
        BrowserCodePolicy.execute(request(enabled_policy()), TimedOutExecutor())


def test_executor_failure_does_not_include_untrusted_exception_text() -> None:
    class FailedExecutor:
        def transform_snapshot_json(
            self,
            script: str,
            timeout_ms: int = 750,
            max_result_bytes: int = 16_384,
        ) -> str:
            raise RuntimeError("untrusted page text must not enter the error")

    with pytest.raises(BrowserCodeExecutionFailed) as error:
        BrowserCodePolicy.execute(request(enabled_policy()), FailedExecutor())

    assert "untrusted page text" not in str(error.value)


def test_executor_response_size_is_checked_before_json_parsing() -> None:
    class OversizedExecutor:
        def transform_snapshot_json(
            self,
            script: str,
            timeout_ms: int = 750,
            max_result_bytes: int = 16_384,
        ) -> str:
            return "{" + " " * 20_000

    with pytest.raises(BrowserCodeValidationError, match="response exceeds"):
        BrowserCodePolicy.execute(request(enabled_policy()), OversizedExecutor())
