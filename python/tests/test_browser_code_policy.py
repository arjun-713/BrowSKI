from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field

from browser_agent.browser_code import (
    BrowserCodeCapability,
    BrowserCodeDisabled,
    BrowserCodePolicy,
    BrowserCodeUnavailable,
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
        "script": "({title: document.title, links: []})",
        "purpose": "extract page summary",
        "reason": "The semantic snapshot omits the visible document title summary.",
        "result_schema": PageSummary,
    }
    values.update(overrides)
    return policy.prepare(**values)  # type: ignore[arg-type]


def test_bounded_extraction_payload_validates_through_local_fake_seam() -> None:
    policy = enabled_policy()
    prepared = request(policy)

    # A local fake supplies the shape a future isolated Rust evaluator would
    # return; no JavaScript is run by this test or by the policy API.
    fake_page_result = {"title": "Fixture page", "links": ["/help"]}
    result = policy.validate_result(prepared, fake_page_result)

    assert isinstance(result, PageSummary)
    assert result.title == "Fixture page"
    assert result.links == ["/help"]
    assert prepared.trace.purpose == "extract page summary"
    assert prepared.trace.script_sha256
    assert "document.title" not in repr(prepared.trace)


def test_capability_is_disabled_by_default() -> None:
    with pytest.raises(BrowserCodeDisabled, match="disabled"):
        request(BrowserCodePolicy())


def test_oversized_script_is_rejected() -> None:
    with pytest.raises(BrowserCodeValidationError, match="8192-byte"):
        request(enabled_policy(), script="x" * 8_193)


def test_timeout_must_fit_hard_upper_bound() -> None:
    with pytest.raises(BrowserCodeValidationError, match="timeout_ms"):
        request(enabled_policy(), timeout_ms=1_501)


def test_executor_remains_fail_closed_even_when_capability_is_enabled() -> None:
    prepared = request(enabled_policy())
    with pytest.raises(BrowserCodeUnavailable, match="isolated, read-only"):
        BrowserCodePolicy.execute(prepared)


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
