"""Validated input and output records for the offline Laya benchmark."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Element(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_id: str | None = None
    ref: str | None = None
    role: str
    name: str | None = None
    text: str | None = None
    value: str | None = None
    state: str | list[str] = Field(default_factory=list)
    interactable: bool | None = None

    @model_validator(mode="after")
    def validate_element_id(self) -> Element:
        if not self.semantic_id and not self.ref:
            raise ValueError("elements require semantic_id or ref")
        return self


class BrowserState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: str
    url: str
    state_generation: int = Field(ge=0)
    elements: list[Element]
    noise_elements: list[Element] = Field(default_factory=list)


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_id: str
    description: str


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    category: str
    difficulty: str
    task: str
    current_subgoal: str
    browser_state: BrowserState
    recent_action: str | None
    recent_outcome: str | None
    relevant_delta: str | None
    constraints: list[str]
    question_type: Literal["choice", "score", "noul"]
    question: str
    candidates: list[Candidate] = Field(default_factory=list)
    criteria: list[str] | dict[str, str] | None = None
    expected_answer: Any
    acceptable_answers: list[Any] = Field(default_factory=list)
    rationale: str
    position_probe: bool = False

    @model_validator(mode="after")
    def validate_question_shape(self) -> BenchmarkCase:
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if self.question_type == "choice":
            if not 2 <= len(self.candidates) <= 16:
                raise ValueError("choice cases require 2 to 16 candidates")
            ids = [candidate.semantic_id for candidate in self.candidates]
            if len(ids) != len(set(ids)):
                raise ValueError("candidate semantic_id values must be unique")
            if self.criteria is not None:
                raise ValueError("Choice cases express criteria through candidates")
        elif self.question_type == "score":
            if (
                not isinstance(self.criteria, (list, dict))
                or not 2 <= len(self.criteria) <= 8
            ):
                raise ValueError("score cases require 2 to 8 score labels in criteria")
            if self.candidates:
                raise ValueError("score cases cannot have candidates")
            if not re.search(
                r"\b(?:proposal|proposed action|proposed sequence|proposed claim)\s*:\s*\S",
                self.question,
                re.IGNORECASE,
            ):
                raise ValueError(
                    "score question must include the exact item being scored, e.g. "
                    "'Proposed action: ...'"
                )
        elif self.question_type == "noul":
            if self.criteria is not None:
                raise ValueError("noul cases cannot have criteria")
        if self.position_probe and self.question_type != "choice":
            raise ValueError("position_probe is supported only for Choice cases")
        return self


def load_cases(path: Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                cases.append(BenchmarkCase.model_validate_json(line))
            except Exception as exc:
                raise ValueError(
                    f"invalid benchmark case at {path}:{line_number}: {exc}"
                ) from exc
    if not cases:
        raise ValueError(f"no benchmark cases found in {path}")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id values must be unique")
    return cases


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as target:
        for row in rows:
            target.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
