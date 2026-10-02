"""Explicit progress, completion evidence, and bounded stagnation detection."""

from __future__ import annotations

from collections import deque
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from browser_agent._types import SemanticSnapshot, SnapshotDelta, TaskState


class ProgressSignal(StrEnum):
    SNAPSHOT_CHANGE = "snapshot_change"
    DOCUMENT_TRANSITION = "document_transition"
    MILESTONE_COMPLETED = "milestone_completed"
    REQUIRED_FACT_ACQUIRED = "required_fact_acquired"
    VERIFICATION_SUCCESS = "verification_success"
    TAB_CHANGED = "tab_changed"
    SUBGOALS_REDUCED = "subgoals_reduced"


class ProgressReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    activity: bool
    progressed: bool
    signals: tuple[ProgressSignal, ...] = ()


class ProgressTracker:
    """Separate browser activity from state changes that advance the task."""

    def compare(
        self,
        before: SemanticSnapshot,
        after: SemanticSnapshot,
        *,
        delta: SnapshotDelta | None = None,
        verification_status: str | None = None,
        completed_milestone: bool = False,
        acquired_required_fact: bool = False,
        outstanding_subgoals_before: int | None = None,
        outstanding_subgoals_after: int | None = None,
    ) -> ProgressReport:
        before_fingerprint = self._semantic_fingerprint(before)
        after_fingerprint = self._semantic_fingerprint(after)
        document_changed = before.url != after.url or before.title != after.title
        tab_changed = before.active_tab != after.active_tab or before.tabs != after.tabs
        snapshot_changed = before_fingerprint != after_fingerprint
        activity = (
            snapshot_changed
            or document_changed
            or tab_changed
            or (delta is not None and not delta.is_empty())
            or verification_status is not None
        )

        signals: list[ProgressSignal] = []
        if snapshot_changed:
            signals.append(ProgressSignal.SNAPSHOT_CHANGE)
        if document_changed:
            signals.append(ProgressSignal.DOCUMENT_TRANSITION)
        if completed_milestone:
            signals.append(ProgressSignal.MILESTONE_COMPLETED)
        if acquired_required_fact:
            signals.append(ProgressSignal.REQUIRED_FACT_ACQUIRED)
        if verification_status == "SUCCESS":
            signals.append(ProgressSignal.VERIFICATION_SUCCESS)
        if tab_changed:
            signals.append(ProgressSignal.TAB_CHANGED)
        if (
            outstanding_subgoals_before is not None
            and outstanding_subgoals_after is not None
            and outstanding_subgoals_after < outstanding_subgoals_before
        ):
            signals.append(ProgressSignal.SUBGOALS_REDUCED)

        return ProgressReport(activity=activity, progressed=bool(signals), signals=tuple(signals))

    @staticmethod
    def _semantic_fingerprint(snapshot: SemanticSnapshot) -> tuple[object, ...]:
        elements = tuple(
            (
                element.ref,
                element.role,
                element.accessible_name,
                element.text,
                element.value,
                tuple(element.state),
                element.interactable,
            )
            for element in snapshot.interactive_elements
        )
        text_blocks = tuple((block.text, tuple(block.frame_path)) for block in snapshot.text_blocks)
        forms = tuple(
            (
                tuple(form.controls),
                form.submit,
                tuple(form.frame_path),
            )
            for form in snapshot.forms
        )
        return (
            snapshot.url,
            snapshot.title,
            snapshot.active_tab,
            snapshot.text_excerpt,
            text_blocks,
            forms,
            elements,
        )


class StagnationSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    state_fingerprint: str
    action_signature: str
    verification_status: str
    progressed: bool = False
    recovery_kind: str | None = None


class StagnationDetector:
    """Bounded detector for repeated states, actions, and unsuccessful recovery."""

    def __init__(
        self,
        window: int = 6,
        *,
        repeat_limit: int = 3,
        uncertainty_limit: int = 3,
        recovery_limit: int = 3,
    ) -> None:
        if window < 3 or repeat_limit < 2 or uncertainty_limit < 2 or recovery_limit < 2:
            raise ValueError("stagnation budgets must be at least two and window at least three")
        self.window = window
        self.repeat_limit = repeat_limit
        self.uncertainty_limit = uncertainty_limit
        self.recovery_limit = recovery_limit
        self._recent: deque[StagnationSample] = deque(maxlen=window)

    def observe(self, sample: StagnationSample | str) -> None:
        """Accept a fingerprint for compatibility or a full decision sample."""
        if isinstance(sample, str):
            sample = StagnationSample(
                state_fingerprint=sample,
                action_signature="",
                verification_status="UNKNOWN",
            )
        self._recent.append(sample)

    @property
    def samples(self) -> tuple[StagnationSample, ...]:
        return tuple(self._recent)

    @property
    def stagnant_steps(self) -> int:
        count = 0
        for sample in reversed(self._recent):
            if sample.progressed:
                break
            count += 1
        return count

    @property
    def is_stagnant(self) -> bool:
        samples = list(self._recent)
        if len(samples) >= 4 and all(not sample.progressed for sample in samples[-4:]):
            fingerprints = [sample.state_fingerprint for sample in samples[-4:]]
            if fingerprints[0] == fingerprints[2] and fingerprints[1] == fingerprints[3]:
                return True
        if len(samples) < self.repeat_limit:
            return False
        recent = samples[-self.repeat_limit :]
        if all(not sample.progressed for sample in recent):
            fingerprints = [sample.state_fingerprint for sample in recent]
            if len(set(fingerprints)) == 1:
                return True

        actions = [sample.action_signature for sample in recent]
        if actions[-1] and len(set(actions)) == 1 and all(not s.progressed for s in recent):
            return True
        if len(samples) >= self.uncertainty_limit and all(
            sample.verification_status == "UNCERTAIN" and not sample.progressed
            for sample in samples[-self.uncertainty_limit :]
        ):
            return True
        if len(samples) >= self.recovery_limit and all(
            sample.recovery_kind is not None and not sample.progressed
            for sample in samples[-self.recovery_limit :]
        ):
            return True
        return False

    def reset(self) -> None:
        self._recent.clear()


def check_completion(
    task: TaskState,
    snapshot: SemanticSnapshot,
    *,
    verified_action: bool,
    semantic_probability: float | None = None,
    semantic_threshold: float = 0.9,
) -> bool:
    """Require task criteria and deterministic browser evidence, never DONE alone."""
    if not verified_action:
        return False
    if not set(task.required_milestones).issubset(task.completed):
        return False

    visible_state = "\n".join(
        [snapshot.url, snapshot.title or "", snapshot.text_excerpt or ""]
        + [block.text for block in snapshot.text_blocks]
        + [element.accessible_name or "" for element in snapshot.elements]
        + [element.text or "" for element in snapshot.elements]
    ).casefold()
    if any(evidence.casefold() not in visible_state for evidence in task.required_evidence):
        return False
    if semantic_probability is not None and semantic_probability < semantic_threshold:
        return False
    return True
