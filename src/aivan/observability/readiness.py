from __future__ import annotations

import os
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse


router = APIRouter(tags=["observability"])
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def readiness_checks() -> dict[str, bool]:
    production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    if not production:
        return {"environment_non_production": True}
    candidate = os.environ.get("AIVAN_CANDIDATE_SHA", "").strip()
    database_url = os.environ.get("AIVAN_DB_URL", "").strip()
    cors = {item.strip() for item in os.environ.get("AIVAN_CORS_ORIGINS", "").split(",") if item.strip()}
    port = os.environ.get("AIVAN_PORT", "").strip()
    roles = [item.strip() for item in os.environ.get("AIVAN_UI_ALLOWED_ROLES", "").split(",") if item.strip()]
    checks = {
        "candidate_frozen": bool(_SHA.fullmatch(candidate)),
        "database_profile_sqlite": database_url == "sqlite:///./data/aivan.db",
        "tenant_configured": _configured("AIVAN_TENANT_ID") or os.environ.get("AIVAN_TENANT_API_KEYS", "").strip() not in {"", "{}"},
        "api_auth_configured": _configured("AIVAN_API_KEY") or _configured("AIVAN_AUTH_SECRET") or os.environ.get("AIVAN_TENANT_API_KEYS", "").strip() not in {"", "{}"},
        "ui_session_secret_configured": len(os.environ.get("AIVAN_UI_SESSION_SECRET", "").strip()) >= 32,
        "ui_identity_configured": _configured("AIVAN_UI_ACTOR_ID") and bool(roles),
        "cors_myaivan_exact": "https://myaivan.com" in cors and "*" not in cors,
        "protected_ports_avoided": bool(port) and port not in {"443", "8443"},
        "gpm_durable_configured": _configured("GIRAFFE_DB_BASE_URL"),
        "openclaw_live_configured": _configured("OPENCLAW_BASE_URL") and os.environ.get("OPENCLAW_MOCK_MODE", "").strip().lower() == "false",
        "local_model_configured": os.environ.get("AIVAN_LLM_PROVIDER", "").strip().lower() == "ollama" and _configured("OLLAMA_BASE_URL"),
        "translation_service_configured": os.environ.get("AIVAN_LANGUAGE_SKILL_ENABLED", "").strip().lower() == "true" and _configured("AIVAN_LANGUAGE_SKILL_BASE_URL"),
        "translation_provider_not_mock": os.environ.get("AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER", "").strip().lower() not in {"", "mock"},
        "translation_backend_declared": _configured("AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL") or _configured("AIVAN_LANGUAGE_SKILL_EXPECTED_BACKEND"),
        "qwen_proofreading_only": os.environ.get("AIVAN_TRANSLATION_PROOFREAD_ENABLED", "").strip().lower() == "true" and os.environ.get("OLLAMA_MODEL", "").strip() == "qwen3.5:9b",
        "non_china_policy_declared": os.environ.get("AIVAN_NON_CHINA_EGRESS_POLICY", "").strip() == "abcdyi-sin",
    }
    return checks


@router.get("/readyz")
def ready():
    checks = readiness_checks()
    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": checks},
    )
