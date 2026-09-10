"""Checkpoint storage contract (Milestone 5)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RunStore(ABC):
    @abstractmethod
    async def save_checkpoint(self, run_id: str, state: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def load_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        raise NotImplementedError
