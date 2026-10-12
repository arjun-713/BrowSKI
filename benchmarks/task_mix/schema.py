"""Typed records and invariants for the seeded local browser task mix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Difficulty = Literal["small", "medium", "large"]
Split = Literal["development", "holdout"]
UserOutcome = Literal["none", "ask_user", "confirmation_required"]
ConfirmationStatus = Literal["none", "pending", "approved", "denied"]

ACTION_RANGES: dict[Difficulty, tuple[int, int]] = {
    "small": (1, 2),
    "medium": (3, 5),
    "large": (6, 10),
}


@dataclass(frozen=True, slots=True)
class GoldState:
    """Independent browser-visible checks for one task's terminal state."""

    inputs: dict[str, str]
    checked: dict[str, bool]
    selected: dict[str, str]
    visible_text: tuple[str, ...]
    tab_paths: tuple[str, ...]
    user_outcome: UserOutcome = "none"
    confirmation_status: ConfirmationStatus = "none"
    submitted: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> GoldState:
        return cls(
            inputs=dict(raw.get("inputs", {})),
            checked=dict(raw.get("checked", {})),
            selected=dict(raw.get("selected", {})),
            visible_text=tuple(raw.get("visible_text", ())),
            tab_paths=tuple(raw.get("tab_paths", ())),
            user_outcome=raw.get("user_outcome", "none"),
            confirmation_status=raw.get("confirmation_status", "none"),
            submitted=bool(raw.get("submitted", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "inputs": self.inputs,
            "checked": self.checked,
            "selected": self.selected,
            "visible_text": list(self.visible_text),
            "tab_paths": list(self.tab_paths),
            "user_outcome": self.user_outcome,
            "confirmation_status": self.confirmation_status,
            "submitted": self.submitted,
        }


@dataclass(frozen=True, slots=True)
class TaskCase:
    case_id: str
    split: Split
    difficulty: Difficulty
    fixture: str
    start_path: str
    task: str
    gold_action_count: int
    max_steps: int
    max_reasoning_calls: int
    max_seconds: int
    gold: GoldState

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> TaskCase:
        case = cls(
            case_id=str(raw["case_id"]),
            split=raw["split"],
            difficulty=raw["difficulty"],
            fixture=str(raw["fixture"]),
            start_path=str(raw["start_path"]),
            task=str(raw["task"]),
            gold_action_count=int(raw["gold_action_count"]),
            max_steps=int(raw["max_steps"]),
            max_reasoning_calls=int(raw["max_reasoning_calls"]),
            max_seconds=int(raw["max_seconds"]),
            gold=GoldState.from_mapping(raw["gold"]),
        )
        case.validate()
        return case

    def validate(self) -> None:
        if not self.case_id or not self.task.strip():
            raise ValueError("case_id and task must be non-empty")
        if not self.fixture.strip():
            raise ValueError(f"{self.case_id}: fixture must be non-empty")
        low, high = ACTION_RANGES[self.difficulty]
        if not low <= self.gold_action_count <= high:
            raise ValueError(
                f"{self.case_id}: {self.difficulty} tasks must have "
                f"{low}-{high} intended actions"
            )
        if self.max_steps < self.gold_action_count:
            raise ValueError(f"{self.case_id}: max_steps is below intended actions")
        if self.max_reasoning_calls < 0 or self.max_seconds < 1:
            raise ValueError(f"{self.case_id}: invalid runtime bounds")
        if not self.start_path.startswith("/"):
            raise ValueError(f"{self.case_id}: start_path must be a local path")
        if self.gold.confirmation_status == "pending":
            if self.gold.user_outcome != "confirmation_required":
                raise ValueError("pending confirmation requires confirmation_required")
            if self.gold.submitted:
                raise ValueError("confirmation holdout must never be submitted")
        if self.gold.user_outcome == "ask_user" and self.gold.submitted:
            raise ValueError("ask_user tasks cannot cause a submission")

    def with_base_url(self, base_url: str) -> dict[str, Any]:
        row = self.as_dict()
        origin = base_url.rstrip("/")
        row["start_url"] = f"{origin}{self.start_path}"
        row["gold"]["tab_urls"] = [f"{origin}{path}" for path in self.gold.tab_paths]
        row["task"] = self.task.replace("{base_url}", origin)
        return row

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "difficulty": self.difficulty,
            "fixture": self.fixture,
            "start_path": self.start_path,
            "task": self.task,
            "gold_action_count": self.gold_action_count,
            "max_steps": self.max_steps,
            "max_reasoning_calls": self.max_reasoning_calls,
            "max_seconds": self.max_seconds,
            "gold": self.gold.as_dict(),
        }
