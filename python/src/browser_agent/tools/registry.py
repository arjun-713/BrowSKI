"""Typed tool registry: JSON-schema tools the model may call.

Rule: browser automation lives in tools, not in prompts. Tools bridge into
the Rust runtime; the model resolves ambiguity, it does not perform
mechanical reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict[str, Any])


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def names(self) -> list[str]:
        return sorted(self._tools)

    def openai_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters or {"type": "object", "properties": {}},
                },
            }
            for spec in (self._tools[name] for name in self.names())
        ]
