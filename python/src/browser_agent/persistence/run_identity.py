"""Validation and generation of identifiers stored in checkpoint metadata."""

from __future__ import annotations

import re
import uuid

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_RUN_ID_ERROR = (
    "run identifier must be a non-sensitive slug of 1 to 64 ASCII letters, "
    "digits, underscores, or hyphens, beginning with a letter or digit"
)


def new_run_id() -> str:
    """Create an opaque UUID suitable for checkpoint and metadata columns."""
    return str(uuid.uuid4())


def validate_run_id(value: object) -> str:
    """Return a bounded run identifier without including rejected input in errors."""
    if not isinstance(value, str) or _RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(_RUN_ID_ERROR)
    return value


def resolve_run_id(value: object | None) -> str:
    """Generate an ID when absent; validate caller-provided values unchanged."""
    if value is None:
        return new_run_id()
    return validate_run_id(value)
