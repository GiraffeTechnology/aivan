"""CORS allowlist for the AIVAN API."""

from __future__ import annotations

import os

from aivan.observability.public_origin import browser_origin, resolved_public_origin


def cors_origins() -> list[str]:
    """Return an explicit CORS allowlist; production defaults to no origins.

    The resolved public origin is always allowed, so no origin or port has to
    be listed by hand.
    """

    configured = os.environ.get("AIVAN_CORS_ORIGINS", "")
    origins = [value.strip() for value in configured.split(",") if value.strip()]
    if "*" in origins:
        raise RuntimeError("AIVAN_CORS_ORIGINS must not contain '*' ")
    public_origin = resolved_public_origin()
    if public_origin:
        origins.append(browser_origin(public_origin))
    if origins:
        return list(dict.fromkeys(origins))
    if os.environ.get("AIVAN_ENV", "local").strip().lower() == "production":
        return []
    port = os.environ.get("AIVAN_PORT", "").strip()
    if not port.isdigit():
        return []
    return [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
