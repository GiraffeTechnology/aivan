from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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
        "database_profile_sqlite": database_url == "sqlite:///./data/aivan.db",
        "tenant_configured": _configured("AIVAN_TENANT_ID") or _tenant_keys_configured(),
        "api_auth_configured": _configured("AIVAN_API_KEY")
        or _configured("AIVAN_AUTH_SECRET")
        or _tenant_keys_configured(),
        "ui_session_secret_configured": len(os.environ.get("AIVAN_UI_SESSION_SECRET", "").strip())
        >= 32,
        "ui_identity_configured": _configured("AIVAN_UI_ACTOR_ID") and bool(roles),
        "cors_myaivan_exact": any(origin == "https://myaivan.com" for origin in cors)
        and "*" not in cors,
        "protected_ports_avoided": bool(port) and port not in {"443", "8443"},
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
