"""Unified service-tenant resolver.

Every AIVAN subsystem that talks to a shared private-domain service (GLTG v2,
giraffe-db graph persistence, the language skill, GPM) must resolve the service
tenant id through this single function. No module may invent its own tenant
fallback chain — that is how AIVAN, GLTG, and giraffe-db end up disagreeing
about which tenant a record belongs to.
"""

from __future__ import annotations

import os

# Order matters: the most specific/authoritative variable wins.
_TENANT_ENV_VARS = (
    "AIVAN_TENANT_ID",
    "GIRAFFE_DB_TENANT_ID",
    "GIRAFFE_TENANT_ID",
)

DEFAULT_SERVICE_TENANT_ID = "server_e2e"


def resolve_service_tenant_id() -> str:
    """Resolve the tenant id used for all cross-service private-domain calls."""
    for name in _TENANT_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return DEFAULT_SERVICE_TENANT_ID
