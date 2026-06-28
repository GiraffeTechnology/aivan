"""Verify the skill manifest points at a real, registered AIVAN route."""

from __future__ import annotations

import json
from pathlib import Path

from aivan.api.main import app

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "skill.json"


def _route_methods() -> dict[str, set[str]]:
    methods: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue
        methods.setdefault(path, set()).update(getattr(route, "methods", set()) or set())
    return methods


def test_manifest_endpoint_is_registered():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    endpoint = manifest["endpoint"]
    method = manifest["method"].upper()

    routes = _route_methods()
    assert endpoint in routes, f"manifest endpoint {endpoint} is not a registered route"
    assert method in routes[endpoint], f"{endpoint} does not accept {method}"


def test_manifest_health_route_is_registered():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    health = manifest["health"]
    assert health in _route_methods()
