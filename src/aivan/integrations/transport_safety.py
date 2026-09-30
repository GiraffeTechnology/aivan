"""Keep test-only HTTP transports out of the production runtime."""

from __future__ import annotations

import os
from typing import Any


def reject_test_transport_in_production(
    transport: Any | None, *, component: str
) -> None:
    if (
        transport is not None
        and os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    ):
        raise RuntimeError(f"{component} test transport is forbidden in production")
