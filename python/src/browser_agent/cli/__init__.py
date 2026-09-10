"""CLI: ``agent run`` / ``agent resume`` / ``agent inspect`` / ``agent benchmark``.

Only ``agent run`` (vertical slice: navigate + observe) is wired in v0.1;
the rest print their milestone status.
"""

from browser_agent.cli.main import app, main

__all__ = ["app", "main"]
