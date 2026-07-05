"""Shared environment-variable parsing helpers."""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env var; unset returns ``default``.

    Any value outside {1, true, yes, on} (case-insensitive) is False.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY
