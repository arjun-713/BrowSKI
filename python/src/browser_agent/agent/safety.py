"""Small deterministic risk policy for consequential browser actions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from browser_agent._types import BrowserAction, SemanticSnapshot


class RiskCategory(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: RiskCategory
    reason: str


class ActionRiskPolicy:
    """Classify form submissions and consequential controls before execution."""

    _HIGH_RISK_WORDS = frozenset(
        {
            "submit",
            "send",
            "purchase",
            "buy",
            "delete",
            "remove",
            "publish",
            "security",
            "financial",
            "transfer",
            "pay",
        }
    )
    _LOW_RISK_ACTIONS = frozenset(
        {"navigate", "back", "forward", "reload", "scroll", "activate_tab", "new_tab"}
    )

    def assess(self, action: BrowserAction, snapshot: SemanticSnapshot) -> RiskAssessment:
        if action.submit:
            return RiskAssessment(category=RiskCategory.HIGH, reason="explicit submit action")
        if action.type in self._LOW_RISK_ACTIONS:
            return RiskAssessment(
                category=RiskCategory.LOW, reason=f"{action.type} is read/navigation"
            )
        if action.type in {"type", "select", "check"}:
            return RiskAssessment(category=RiskCategory.MEDIUM, reason="form state change")

        target_ref = action.target.ref if action.target else None
        if action.type == "press" and (action.key or "").casefold() in {"enter", "return"}:
            return RiskAssessment(category=RiskCategory.HIGH, reason="Enter may submit a form")
        if target_ref and any(form.submit == target_ref for form in snapshot.forms):
            return RiskAssessment(category=RiskCategory.HIGH, reason="form submission")

        target = next(
            (element for element in snapshot.elements if element.ref == target_ref),
            None,
        )
        label = " ".join(
            part
            for part in (
                target.accessible_name if target else None,
                target.text if target else None,
            )
            if part
        ).casefold()
        words = set(label.replace("/", " ").replace("-", " ").split())
        matched = sorted(words & self._HIGH_RISK_WORDS)
        if matched:
            return RiskAssessment(
                category=RiskCategory.HIGH,
                reason=f"consequential control label: {', '.join(matched)}",
            )
        if action.type in {"click", "press", "handle_dialog", "close_tab"}:
            return RiskAssessment(category=RiskCategory.MEDIUM, reason="page state change")
        return RiskAssessment(category=RiskCategory.LOW, reason="non-consequential action")
