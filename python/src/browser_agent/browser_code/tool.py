"""Typed adapter between Luna's proposal and the isolated Rust executor."""

from __future__ import annotations

from browser_agent.browser_code.contracts import (
    BrowserCodePayload,
    BrowserCodeProposal,
    BrowserCodeResult,
)
from browser_agent.browser_code.policy import (
    BrowserCodeCapability,
    BrowserCodeExecution,
    BrowserCodeExecutor,
    BrowserCodePolicy,
    BrowserCodeRequest,
)


class BrowserCodeTool:
    """Execute only the fixed-schema semantic projection transform capability."""

    def __init__(self, *, enabled: bool = False) -> None:
        self._policy = BrowserCodePolicy(BrowserCodeCapability(enabled=enabled))

    def prepare(self, proposal: BrowserCodeProposal) -> BrowserCodeRequest:
        """Validate the proposal and return source-free trace metadata with it."""
        return self._policy.prepare(
            script=proposal.script,
            purpose=proposal.purpose,
            reason=proposal.reason,
            result_schema=BrowserCodePayload,
            timeout_ms=proposal.timeout_ms,
            max_result_bytes=proposal.max_result_bytes,
        )

    def execute_prepared(
        self,
        request: BrowserCodeRequest,
        executor: BrowserCodeExecutor,
    ) -> BrowserCodeResult:
        """Run a prepared request against session-owned Rust snapshot data."""
        execution: BrowserCodeExecution = self._policy.execute(request, executor)
        return BrowserCodeResult(
            state_generation=execution.state_generation,
            payload=BrowserCodePayload.model_validate(execution.result),
        )

    def execute(
        self,
        proposal: BrowserCodeProposal,
        executor: BrowserCodeExecutor,
    ) -> BrowserCodeResult:
        """Prepare and run one transform as a convenience for local callers."""
        return self.execute_prepared(self.prepare(proposal), executor)
