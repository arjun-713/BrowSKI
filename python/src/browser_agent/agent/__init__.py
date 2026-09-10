"""Agent runtime: :class:`Agent` / :class:`AgentRuntime` and the agent loop.

Milestone 4 target loop: UNDERSTAND -> PLAN -> OBSERVE -> DECIDE -> ACT ->
VERIFY -> UPDATE -> CHECK PROGRESS -> RECOVER -> REPEAT.

Not implemented in the scaffold; this module defines the lifecycle contract
so later milestones slot in without redesigning cross-language APIs.
"""

from browser_agent.agent.runtime import Agent, AgentRuntime

__all__ = ["Agent", "AgentRuntime"]
