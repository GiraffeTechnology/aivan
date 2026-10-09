from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from aivan.app.ui_catalog import GENERATED_LOCALES, ready_locales


router = APIRouter(tags=["observability"])
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _tenant_keys_configured() -> bool:
    raw = os.environ.get("AIVAN_TENANT_API_KEYS", "").strip()
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return (
        bool(parsed)
        and isinstance(parsed, dict)
        and all(
            isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip()
            for key, value in parsed.items()
        )
    )


def _database_profile_configured(database_url: str) -> bool:
    """Validate selected SQL configuration without connecting or exposing it.

    Runtime state uses a synchronous SQLAlchemy engine. Installer external mode
    must not silently become SQLite; an unset mode preserves source deployments.
    This is configuration evidence, not proof of connectivity or schema health.
    """
    mode = os.environ.get("MYAIVAN_DATABASE_MODE", "").strip().lower()
    if mode not in {"", "external", "isolated"} or not database_url:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in database_url):
        return False
    try:
        url = make_url(database_url)
        dialect = url.get_dialect()
    except (ArgumentError, ImportError, TypeError, ValueError):
        return False
    if dialect.is_async or not url.database:
        return False
    if url.port is not None and not 1 <= url.port <= 65535:
        return False
    if url.host and any(character.isspace() for character in url.host):
        return False
    sqlite = dialect.name == "sqlite"
    if (mode == "external" and sqlite) or (mode == "isolated" and not sqlite):
        return False
    if sqlite:
        if url.host or url.username or url.password or url.port is not None:
            return False
        if (url.database == ":memory:" or url.database.startswith("file::memory:")
                or url.query.get("mode") == "memory"):
            return False
    return True


def _configured_port_avoids_reservations(port: str) -> bool:
    def valid(value: str) -> bool:
        return bool(re.fullmatch(r"[1-9][0-9]{0,4}", value)) and int(value) <= 65535

    if not valid(port):
        return False
    raw = os.environ.get("AIVAN_RESERVED_PORTS", "").strip()
    reserved = [value.strip() for value in raw.split(",")] if raw else []
    return all(valid(value) for value in reserved) and port not in reserved


def readiness_checks() -> dict[str, bool]:
    production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    if not production:
        return {"environment_non_production": True}
    candidate = os.environ.get("AIVAN_CANDIDATE_SHA", "").strip()
    database_url = os.environ.get("AIVAN_DB_URL", "").strip()
    cors = {
        item.strip() for item in os.environ.get("AIVAN_CORS_ORIGINS", "").split(",") if item.strip()
    }
    port = os.environ.get("AIVAN_PORT", "").strip()
    roles = [
        item.strip()
        for item in os.environ.get("AIVAN_UI_ALLOWED_ROLES", "").split(",")
        if item.strip()
    ]
    checks = {
        "candidate_frozen": bool(_SHA.fullmatch(candidate)),
        "database_profile_configured": _database_profile_configured(database_url),
        "tenant_configured": _configured("AIVAN_TENANT_ID") or _tenant_keys_configured(),
        "api_auth_configured": _configured("AIVAN_API_KEY")
        or _configured("AIVAN_AUTH_SECRET")
        or _tenant_keys_configured(),
        "ui_session_secret_configured": len(os.environ.get("AIVAN_UI_SESSION_SECRET", "").strip())
        >= 32,
        "ui_identity_configured": _configured("AIVAN_UI_ACTOR_ID") and bool(roles),
        "cors_myaivan_exact": any(origin == "https://myaivan.com" for origin in cors)
        and "*" not in cors,
        "protected_ports_avoided": _configured_port_avoids_reservations(port),
        "gpm_durable_configured": _configured("GIRAFFE_DB_BASE_URL"),
        "openclaw_live_configured": _configured("OPENCLAW_BASE_URL")
        and os.environ.get("OPENCLAW_MOCK_MODE", "").strip().lower() == "false",
        "local_model_configured": os.environ.get("AIVAN_LLM_PROVIDER", "").strip().lower()
        == "ollama"
        and _configured("OLLAMA_BASE_URL"),
        "translation_service_configured": os.environ.get("AIVAN_LANGUAGE_SKILL_ENABLED", "")
        .strip()
        .lower()
        == "true"
        and _configured("AIVAN_LANGUAGE_SKILL_BASE_URL"),
        "translation_provider_not_mock": os.environ.get(
            "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER", ""
        )
        .strip()
        .lower()
        not in {"", "mock"},
        "translation_backend_declared": _configured("AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL")
        or _configured("AIVAN_LANGUAGE_SKILL_EXPECTED_BACKEND"),
        "qwen_proofreading_only": os.environ.get("AIVAN_TRANSLATION_PROOFREAD_ENABLED", "")
        .strip()
        .lower()
        == "true"
        and os.environ.get("OLLAMA_MODEL", "").strip() == "qwen3.5:9b",
        "non_china_policy_declared": os.environ.get("AIVAN_NON_CHINA_EGRESS_POLICY", "").strip()
        == "abcdyi-sin",
    }
    catalog_ready = set(ready_locales(candidate))
    checks.update(
        {f"ui_catalog_{locale}_ready": locale in catalog_ready for locale in GENERATED_LOCALES}
    )
    return checks


@router.get("/readyz")
def ready():
    checks = readiness_checks()
    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": checks},
    )
