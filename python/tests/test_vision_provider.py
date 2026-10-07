"""Fake-provider tests for the optional, on-demand vision boundary."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Protocol, cast

import pytest
from pydantic import ValidationError

from browser_agent._types import AgentObservation, PrunedElement
from browser_agent.providers.privacy import (
    PrivacyMode,
    ProviderBoundaryError,
    VisionProviderBoundary,
)
from browser_agent.reasoning.openai_adapter import ReasoningProviderProtocolError
from browser_agent.vision import (
    MAX_SCREENSHOT_BYTES,
    OpenAILunaVisionProvider,
    ScreenshotMetadata,
    SemanticTargetMetadata,
    VisionInterpretation,
    VisionOutcome,
    VisionRequest,
    interpret_if_semantics_insufficient,
)


class FakeResponses:
    def __init__(self, output_parsed: object | None) -> None:
        self.output_parsed = output_parsed
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.output_parsed)


class ResponsesPort(Protocol):
    async def parse(self, **kwargs: object) -> object: ...


class FakeClient:
    def __init__(self, responses: ResponsesPort) -> None:
        self.responses = responses


class FakeVisionProvider:
    def __init__(self, result: VisionInterpretation) -> None:
        self.result = result
        self.calls = 0

    async def interpret(self, request: VisionRequest) -> VisionInterpretation:
        _ = request
        self.calls += 1
        return self.result


def make_request(*, screenshot: bytes = b"private-image-bytes") -> VisionRequest:
    observation = AgentObservation(
        url="https://example.test/",
        title="Example",
        state_generation=7,
        elements=[PrunedElement(ref="@continue", role="button", name="Continue")],
    )
    return VisionRequest(
        task="Find the continue button",
        observation=observation,
        screenshot=screenshot,
        mime_type="image/png",
        metadata=ScreenshotMetadata(
            viewport_width=1280,
            viewport_height=720,
            active_tab="tab-private-id",
            state_generation=7,
        ),
        targets=[
            SemanticTargetMetadata(
                ref="@continue",
                role="button",
                name="Continue",
                x=100,
                y=200,
                width=120,
                height=40,
            )
        ],
    )


async def test_semantic_route_does_not_invoke_vision_provider() -> None:
    provider = FakeVisionProvider(
        VisionInterpretation(outcome=VisionOutcome.ABSTAIN, confidence=0.0)
    )

    request_count = 0

    def create_request() -> VisionRequest:
        nonlocal request_count
        request_count += 1
        return make_request()

    result = await interpret_if_semantics_insufficient(
        provider,
        create_request,
        semantic_sufficient=True,
    )

    assert result is None
    assert provider.calls == 0
    assert request_count == 0


async def test_insufficient_semantics_routes_to_provider_and_checks_semantic_ref() -> None:
    provider = FakeVisionProvider(
        VisionInterpretation(
            outcome=VisionOutcome.TARGET_IDENTIFIED,
            target_ref="@continue",
            summary="The continue control is visible.",
            confidence=0.91,
        )
    )

    result = await interpret_if_semantics_insufficient(
        provider,
        make_request,
        semantic_sufficient=False,
    )

    assert provider.calls == 1
    assert result is not None
    assert result.target_ref == "@continue"


async def test_openai_vision_adapter_uses_bounded_structured_image_request() -> None:
    responses = FakeResponses(
        {
            "outcome": "target_identified",
            "target_ref": "@continue",
            "summary": "Visible control.",
            "confidence": 0.9,
        }
    )
    provider = OpenAILunaVisionProvider(FakeClient(responses), max_output_tokens=300)

    result = await provider.interpret(make_request())

    assert result.target_ref == "@continue"
    assert len(responses.calls) == 1
    call = responses.calls[0]
    assert call["text_format"] is VisionInterpretation
    assert call["max_output_tokens"] == 300
    assert call["reasoning"] == {"effort": "low"}
    request_input = cast(list[dict[str, object]], call["input"])
    content = cast(list[dict[str, object]], request_input[0]["content"])
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    image_url = cast(str, content[1]["image_url"])
    text_input = cast(str, content[0]["text"])
    assert image_url.endswith(base64.b64encode(b"private-image-bytes").decode())
    assert "screenshot" not in text_input
    assert "tab-private-id" not in text_input
    assert "state_generation" not in text_input


@pytest.mark.parametrize("mode", [PrivacyMode.PRIVACY_FIRST, PrivacyMode.OFFLINE])
async def test_vision_boundary_blocks_unsanitized_screenshots(mode: PrivacyMode) -> None:
    provider = FakeVisionProvider(
        VisionInterpretation(outcome=VisionOutcome.ABSTAIN, confidence=0.0)
    )

    with pytest.raises(ProviderBoundaryError, match="screenshot redaction"):
        await VisionProviderBoundary(provider, mode=mode).interpret(make_request())

    assert provider.calls == 0


async def test_vision_boundary_forwards_only_in_standard_mode() -> None:
    provider = FakeVisionProvider(
        VisionInterpretation(outcome=VisionOutcome.ABSTAIN, confidence=0.0)
    )

    result = await VisionProviderBoundary(provider).interpret(make_request())

    assert result.outcome is VisionOutcome.ABSTAIN
    assert provider.calls == 1


async def test_openai_vision_adapter_rejects_unknown_target_and_coordinates() -> None:
    responses = FakeResponses(
        {
            "outcome": "target_identified",
            "target_ref": "@invented",
            "summary": "Found it.",
            "confidence": 0.9,
        }
    )
    with pytest.raises(ReasoningProviderProtocolError, match="absent from supplied target"):
        await OpenAILunaVisionProvider(FakeClient(responses)).interpret(make_request())

    with pytest.raises(ValidationError):
        VisionInterpretation.model_validate(
            {
                "outcome": "target_identified",
                "target_ref": "@continue",
                "x": 100,
                "y": 200,
                "confidence": 0.9,
            }
        )


def test_vision_request_enforces_image_and_viewport_bounds() -> None:
    with pytest.raises(ValidationError):
        make_request(screenshot=b"x" * (MAX_SCREENSHOT_BYTES + 1))

    with pytest.raises(ValidationError):
        ScreenshotMetadata(
            viewport_width=9000,
            viewport_height=720,
            active_tab="tab-1",
            state_generation=1,
        )


async def test_visual_failures_do_not_expose_underlying_error_message() -> None:
    secret = "private-image-payload"

    class FailingResponses:
        async def parse(self, **kwargs: object) -> object:
            _ = kwargs
            raise RuntimeError(secret)

    from browser_agent.reasoning.openai_adapter import ReasoningProviderRequestError

    with pytest.raises(ReasoningProviderRequestError) as error:
        await OpenAILunaVisionProvider(FakeClient(FailingResponses())).interpret(make_request())
    assert secret not in str(error.value)
