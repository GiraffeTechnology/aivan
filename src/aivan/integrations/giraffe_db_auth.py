"""Select an operator-configured credential for one private-provider tenant."""
from __future__ import annotations

import json
import os
import re
from typing import Literal, TypeGuard

_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


class ServiceAuthError(ValueError):
    """Credential failure that never includes configuration or secret values."""

    def __init__(self, reason: Literal["required", "invalid"]) -> None:
        self.reason = reason
        super().__init__(f"Provider service authentication {reason}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ServiceAuthError("invalid")
        result[key] = value
    return result


def _safe_secret(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and all(33 <= ord(char) < 127 for char in value)
    )


def service_auth_for_tenant(tenant_id: str, *, required: bool = True) -> str:
    """A configured map is authoritative, including when invalid or incomplete.

    The optional shared-key mode preserves the legacy graph client's ability to
    send no credential when no tenant map or shared credential is configured.
    No configured tenant map can fall back to the shared credential.
    """
    if not isinstance(tenant_id, str) or not _TENANT_ID.fullmatch(tenant_id):
        raise ServiceAuthError("invalid")
    raw_mapping = os.environ.get("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON")
    if raw_mapping is not None:
        try:
            mapping = json.loads(raw_mapping, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):
            raise ServiceAuthError("invalid") from None
        if not isinstance(mapping, dict) or not mapping:
            raise ServiceAuthError("invalid")
        credentials: dict[str, str] = {}
        for key, value in mapping.items():
            if (not isinstance(key, str) or not _TENANT_ID.fullmatch(key)
                    or not _safe_secret(value)):
                raise ServiceAuthError("invalid")
            credentials[key] = value
        if tenant_id not in credentials:
            raise ServiceAuthError("required")
        return credentials[tenant_id]

    secret = os.environ.get("GIRAFFE_DB_SERVICE_AUTH_SECRET", "")
    if not secret:
        if required:
            raise ServiceAuthError("required")
        return ""
    if not _safe_secret(secret):
        raise ServiceAuthError("invalid")
    return secret
