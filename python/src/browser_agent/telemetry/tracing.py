"""Structured logging for the Python agent runtime."""

from __future__ import annotations

import structlog


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
