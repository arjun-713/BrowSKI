"""High-level recovery policy (Milestone 6).

Low-level mechanical retries live in Rust (``crates/recovery``) and are always
bounded. This module will own strategy changes: replan, alternate strategy,
escalation to the user. Scaffold defines the interface only.
"""

from __future__ import annotations

from dataclasses import dataclass

from browser_agent._types import FailureKind, RecoveryDecision


@dataclass
class RecoveryPolicy:
    max_replans: int = 3

    def decide(self, kind: FailureKind, attempt: int) -> RecoveryDecision:
        if attempt < self.max_replans:
            return RecoveryDecision(
                decision="replan",
                attempt=attempt + 1,
                max_attempts=self.max_replans,
                reason=f"{kind.value}: trying alternate strategy",
            )
        return RecoveryDecision(
            decision="escalate",
            attempt=attempt,
            max_attempts=self.max_replans,
            reason=f"{kind.value}: exhausted replans",
        )
