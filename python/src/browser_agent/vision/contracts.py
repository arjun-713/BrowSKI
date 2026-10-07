"""Bounded request-scoped visual interpretation contracts."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from browser_agent._types import AgentObservation

MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024
MAX_VIEWPORT_DIMENSION = 8_192
MAX_SEMANTIC_TARGETS = 64


class ScreenshotMetadata(BaseModel):
    """Viewport dimensions associated with one transient screenshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    viewport_width: int = Field(gt=0, le=MAX_VIEWPORT_DIMENSION)
    viewport_height: int = Field(gt=0, le=MAX_VIEWPORT_DIMENSION)
    device_scale_factor: float = Field(default=1.0, gt=0, le=8)
    active_tab: str = Field(min_length=1, max_length=200)
    state_generation: int = Field(ge=0)


class SemanticTargetMetadata(BaseModel):
    """A semantic candidate and optional viewport-relative target rectangle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=2, max_length=200, pattern=r"^@")
    role: str = Field(min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=300)
    x: int | None = Field(default=None, ge=0, le=MAX_VIEWPORT_DIMENSION)
    y: int | None = Field(default=None, ge=0, le=MAX_VIEWPORT_DIMENSION)
    width: int | None = Field(default=None, ge=0, le=MAX_VIEWPORT_DIMENSION)
    height: int | None = Field(default=None, ge=0, le=MAX_VIEWPORT_DIMENSION)

    @model_validator(mode="after")
    def validate_rectangle(self) -> SemanticTargetMetadata:
        rectangle = (self.x, self.y, self.width, self.height)
        if any(value is not None for value in rectangle) and any(
            value is None for value in rectangle
        ):
            raise ValueError("target rectangle must include x, y, width, and height")
        return self


class VisionRequest(BaseModel):
    """A single bounded screenshot and the semantic context needed to interpret it."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    task: str = Field(min_length=1, max_length=2_000)
    observation: AgentObservation
    screenshot: bytes = Field(min_length=1, max_length=MAX_SCREENSHOT_BYTES, repr=False)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    metadata: ScreenshotMetadata
    targets: list[SemanticTargetMetadata] = Field(
        default_factory=lambda: list[SemanticTargetMetadata](),
        max_length=MAX_SEMANTIC_TARGETS,
    )

    @model_validator(mode="after")
    def validate_screenshot_and_targets(self) -> VisionRequest:
        if len(self.screenshot) > MAX_SCREENSHOT_BYTES:
            raise ValueError("screenshot exceeds the configured byte limit")
        refs = {element.ref for element in self.observation.elements}
        if len(self.targets) > MAX_SEMANTIC_TARGETS:
            raise ValueError("too many semantic target candidates")
        if len({target.ref for target in self.targets}) != len(self.targets):
            raise ValueError("semantic target refs must be unique")
        for target in self.targets:
            if target.ref not in refs:
                raise ValueError("target metadata must reference the supplied observation")
            if target.x is not None and (
                target.x + (target.width or 0) > self.metadata.viewport_width
                or target.y is None
                or target.y + (target.height or 0) > self.metadata.viewport_height
            ):
                raise ValueError("target rectangle must fit inside the screenshot viewport")
        return self


class VisionOutcome(StrEnum):
    TARGET_IDENTIFIED = "target_identified"
    INTERPRETATION = "interpretation"
    ABSTAIN = "abstain"


class VisionInterpretation(BaseModel):
    """Constrained visual finding; target selection uses semantic refs only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: VisionOutcome
    summary: str = Field(default="", max_length=1_000)
    target_ref: str | None = Field(default=None, min_length=2, max_length=200, pattern=r"^@")
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_outcome(self) -> VisionInterpretation:
        if (self.outcome == VisionOutcome.TARGET_IDENTIFIED) != (self.target_ref is not None):
            raise ValueError("target_identified requires exactly one semantic target_ref")
        return self


class VisionProvider(Protocol):
    """Provider contract implemented by the optional screenshot interpreter."""

    async def interpret(self, request: VisionRequest) -> VisionInterpretation: ...


async def interpret_if_semantics_insufficient(
    provider: VisionProvider,
    request_factory: Callable[[], VisionRequest],
    *,
    semantic_sufficient: bool,
) -> VisionInterpretation | None:
    """Invoke vision only when the caller has established semantic insufficiency."""
    if semantic_sufficient:
        return None
    request = request_factory()
    result = await provider.interpret(request)
    if result.target_ref is not None:
        valid_refs = {element.ref for element in request.observation.elements}
        if result.target_ref not in valid_refs:
            raise ValueError("vision response selected a ref absent from the supplied observation")
        candidate_refs = {target.ref for target in request.targets}
        if result.target_ref not in candidate_refs:
            raise ValueError("vision response selected a ref absent from supplied target metadata")
    return result
