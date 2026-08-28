from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from aivan.governance.runtime_policy import (
    BUSINESS_FACT_AUTHORITY,
    LOCAL_STATE_SCOPE,
    PRODUCT_ROLE,
    PROHIBITED_CAPABILITY_FLAGS,
    RuntimePolicyError,
    enforce_runtime_policy,
    production_policy_checks,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "aivan"


def _production_safe(monkeypatch) -> None:
    values = {
        "AIVAN_ENV": "production",
        "AIVAN_PRODUCT_ROLE": PRODUCT_ROLE,
        "AIVAN_BUSINESS_FACT_AUTHORITY": BUSINESS_FACT_AUTHORITY,
        "AIVAN_LOCAL_STATE_SCOPE": LOCAL_STATE_SCOPE,
        "AIVAN_REQUIRE_HUMAN_APPROVAL": "true",
        "AIVAN_ALLOW_STUB_SUPPLIERS": "false",
        "OPENCLAW_MOCK_MODE": "false",
        "AIVAN_LLM_PROVIDER": "ollama",
        "GPM_LLM_RUNTIME_MODE": "live",
        "AIVAN_WEB_SEARCH_PROVIDER": "openclaw_search",
        "AIVAN_ALIBABA_MODE": "official_api",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER": "ctranslate2",
        "AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED": "false",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in PROHIBITED_CAPABILITY_FLAGS:
        monkeypatch.delenv(name, raising=False)


def test_production_policy_accepts_only_frozen_control_plane_boundary(monkeypatch):
    _production_safe(monkeypatch)
    assert all(production_policy_checks().values())
    enforce_runtime_policy(component="test")


@pytest.mark.parametrize(
    ("name", "value", "failed_check"),
    [
        ("AIVAN_PRODUCT_ROLE", "standalone_worker", "product_role_control_plane"),
        ("AIVAN_BUSINESS_FACT_AUTHORITY", "local", "business_fact_authority_giraffe_db"),
        ("AIVAN_LOCAL_STATE_SCOPE", "business_facts", "local_state_control_audit_cache_only"),
        ("AIVAN_REQUIRE_HUMAN_APPROVAL", "false", "human_approval_required"),
        ("AIVAN_ALLOW_STUB_SUPPLIERS", "true", "stub_suppliers_disabled"),
        ("OPENCLAW_MOCK_MODE", "true", "openclaw_mock_disabled"),
        ("AIVAN_LLM_PROVIDER", "mock", "llm_mock_disabled"),
        ("GPM_LLM_RUNTIME_MODE", "mock", "gpm_mock_disabled"),
        ("AIVAN_WEB_SEARCH_PROVIDER", "mock", "web_search_mock_disabled"),
        ("AIVAN_ALIBABA_MODE", "mock", "marketplace_mock_disabled"),
        ("AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER", "mock", "language_mock_disabled"),
        (
            "AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED",
            "true",
            "external_model_auto_disabled",
        ),
    ],
)
def test_production_policy_fails_closed_for_each_forbidden_mode(
    monkeypatch, name, value, failed_check
):
    _production_safe(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimePolicyError) as raised:
        enforce_runtime_policy(component="test")
    assert failed_check in raised.value.failed_checks
    assert name not in str(raised.value)


@pytest.mark.parametrize("name", PROHIBITED_CAPABILITY_FLAGS)
def test_runtime_code_capability_flags_are_always_denied(monkeypatch, name):
    _production_safe(monkeypatch)
    monkeypatch.setenv(name, "true")
    with pytest.raises(RuntimePolicyError) as raised:
        enforce_runtime_policy(component="test")
    assert raised.value.failed_checks == ("code_capabilities_disabled",)


def test_non_production_retains_explicit_test_seams(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "test")
    monkeypatch.setenv("OPENCLAW_MOCK_MODE", "true")
    assert production_policy_checks() == {"environment_non_production": True}
    enforce_runtime_policy(component="test")


def test_production_rejects_fake_dependency_transports(monkeypatch):
    from aivan.integrations.gltg_client import GLTGClient, set_default_transport as set_gltg
    from aivan.integrations.language_skill_client import (
        LanguageSkillClient,
        set_default_transport as set_language,
    )

    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    _production_safe(monkeypatch)
    with pytest.raises(RuntimePolicyError, match="test_transport_disabled"):
        GLTGClient(transport=transport)
    with pytest.raises(RuntimePolicyError, match="test_transport_disabled"):
        LanguageSkillClient(transport=transport)
    with pytest.raises(RuntimePolicyError, match="test_transport_disabled"):
        set_gltg(transport)
    with pytest.raises(RuntimePolicyError, match="test_transport_disabled"):
        set_language(transport)


def test_production_giraffe_context_never_uses_local_placeholder_facts(
    monkeypatch, db_session
):
    from aivan.integrations.giraffe_db import GiraffeDBClient
    from aivan.schemas.requirement import BuyerRequirement

    _production_safe(monkeypatch)
    requirement = BuyerRequirement(raw_text="100 shirts")
    with pytest.raises(RuntimeError, match="GIRAFFE_DB_CANONICAL_CONTEXT_REQUIRED"):
        GiraffeDBClient(db_session, tenant_id="tenant-a").build_context(requirement)


def test_production_risk_search_never_falls_back_to_mock(monkeypatch):
    from aivan.risk.search_providers import OpenClawSearchProvider, get_search_provider_for_risk

    _production_safe(monkeypatch)
    monkeypatch.delenv("OPENCLAW_BASE_URL", raising=False)
    assert OpenClawSearchProvider().search("supplier") == []
    monkeypatch.setenv("AIVAN_WEB_SEARCH_PROVIDER", "mock")
    with pytest.raises(RuntimeError, match="MOCK_RISK_SEARCH_FORBIDDEN"):
        get_search_provider_for_risk()


def test_production_llm_and_openclaw_cannot_construct_mock_clients(monkeypatch):
    from aivan.llm.gateway import _build_provider
    from aivan.openclaw.client import OpenClawClient

    _production_safe(monkeypatch)
    with pytest.raises(RuntimeError, match="MOCK_LLM_FORBIDDEN"):
        _build_provider("mock")
    monkeypatch.setenv("OPENCLAW_MOCK_MODE", "true")
    with pytest.raises(RuntimeError, match="OPENCLAW_MOCK_FORBIDDEN"):
        OpenClawClient()


def test_openclaw_client_returns_stable_error_not_remote_exception(monkeypatch):
    from aivan.openclaw.client import OpenClawClient

    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("OPENCLAW_MOCK_MODE", "false")
    monkeypatch.setenv("OPENCLAW_BASE_URL", "http://127.0.0.1:3000")

    def fail(*_args, **_kwargs):
        raise RuntimeError("secret-token and remote response body")

    monkeypatch.setattr(httpx, "get", fail)
    result = OpenClawClient().check_account_status("account-1")
    assert result["status"] == "error"
    assert result["error"].startswith("OPENCLAW_REQUEST_FAILED:")
    assert "secret-token" not in result["error"]


def test_dependency_clients_never_return_remote_body_or_exception_text(monkeypatch):
    from aivan.integrations.gltg_client import GLTGClient
    from aivan.integrations.language_skill_client import LanguageSkillClient

    monkeypatch.setenv("AIVAN_ENV", "local")
    secret_body = "upstream-secret-response"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(503, text=secret_body)
    )
    gltg = GLTGClient(transport=transport).health()
    language = LanguageSkillClient(transport=transport).health()
    assert gltg.error == "GLTG_HTTP_503"
    assert language.error == "LANGUAGE_SKILL_HTTP_503"
    assert secret_body not in str(gltg)
    assert secret_body not in str(language)


def test_production_cli_rejects_demo_and_import_commands(monkeypatch):
    from aivan.cli.main import main

    _production_safe(monkeypatch)
    for command in ("demo", "import-suppliers", "test"):
        monkeypatch.setattr("sys.argv", ["aivan", command])
        with pytest.raises(SystemExit) as raised:
            main()
        assert raised.value.code == 2


def test_gpm_defaults_loopback_and_requires_auth_for_public_bind(monkeypatch):
    from aivan.gpm.server import (
        DEFAULT_HOST,
        PUBLIC_BIND_AUTH_ERROR,
        validate_bind_host,
    )

    assert DEFAULT_HOST == "127.0.0.1"
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    validate_bind_host("127.0.0.1")
    monkeypatch.setenv("AIVAN_API_KEY", "not-a-gpm-public-auth-profile")
    monkeypatch.setenv("AIVAN_TENANT_API_KEYS", '{"tenant-a":"also-not-sufficient"}')
    with pytest.raises(RuntimeError, match=PUBLIC_BIND_AUTH_ERROR):
        validate_bind_host("0.0.0.0")
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "injected")
    validate_bind_host("0.0.0.0")


def test_packaged_runtime_has_no_code_or_repository_execution_primitives():
    forbidden_import_roots = {"subprocess", "git", "pygit2", "dulwich"}
    forbidden_calls = {"eval", "exec", "compile"}
    findings: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in forbidden_import_roots:
                        findings.append(f"{path.relative_to(ROOT)}:{node.lineno}:import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".", 1)[0] in forbidden_import_roots:
                    findings.append(f"{path.relative_to(ROOT)}:{node.lineno}:from {node.module}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                    findings.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.func.id}")
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    if (node.func.value.id, node.func.attr) in {
                        ("os", "system"),
                        ("os", "popen"),
                    }:
                        findings.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}:"
                            f"{node.func.value.id}.{node.func.attr}"
                        )
                if any(
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in node.keywords
                ):
                    findings.append(f"{path.relative_to(ROOT)}:{node.lineno}:shell=True")
    assert findings == []


def test_product_boundary_is_versioned_in_docs_and_environment_schema():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    adr = (ROOT / "docs/adr/0003-control-plane-runtime-boundary.md").read_text(
        encoding="utf-8"
    )
    production = (ROOT / "deploy/aivan.production.env.example").read_text(
        encoding="utf-8"
    )
    matrix = (
        ROOT / "docs/architecture/aivan-control-plane-responsibility-matrix.md"
    ).read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    plugin = (
        ROOT / "integrations/openclaw-aivan-plugin/README.md"
    ).read_text(encoding="utf-8")
    assert "Standalone Product" not in readme
    assert "monitoring and human-takeover control plane" in readme
    assert "trade monitoring and human-takeover control plane" in project
    assert "standalone, local-first AI assistant" not in plugin
    assert "human-takeover control plane" in plugin
    assert "giraffe-db" in matrix
    assert "Code and repository operations" in matrix
    for assignment in (
        f"AIVAN_PRODUCT_ROLE={PRODUCT_ROLE}",
        f"AIVAN_BUSINESS_FACT_AUTHORITY={BUSINESS_FACT_AUTHORITY}",
        f"AIVAN_LOCAL_STATE_SCOPE={LOCAL_STATE_SCOPE}",
    ):
        assert assignment in production
        assert assignment in adr
