#!/usr/bin/env python3
"""AIVAN production operational smoke test (post-PR29).

Exercises the private-domain safety invariants against the configured local
model (on CTYUN: ollama + qwen3.5:2b). Each scenario asserts SAFETY, not model
accuracy: no external API call, no silent mock fallback, no outbound before
approval, correct gating, and deterministic fallback on local-model failure.

Scenarios:
  1. Normal Chinese RFQ            -> safe pending action, Chinese reply, no debug leak
  2. Missing destination RFQ       -> pending_destination_confirmation, no drafts, no GLTG
  3. Supplier count < 3            -> pending confirmation/selection, never an error
  4. Local model failure           -> deterministic fallback (no mock, no cloud)
  5. Production auth fail-closed    -> protected routes rejected, health open

Runnable anywhere: with a live Ollama it uses it; without one, scenario 1/4
naturally exercise the local-model-unavailable path (still safe). Prints the
real provider telemetry it observed.

Usage:
    uv run python scripts/run_aivan_prod_smoke.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_DB_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from aivan.db.models import Base  # noqa: E402
import aivan.execution.rfq_execution as rfqe  # noqa: E402
from aivan.execution.rfq_execution import create_rfq_from_event  # noqa: E402
from aivan.llm import gateway  # noqa: E402
from aivan.openclaw.contracts import OpenClawEvent  # noqa: E402
from aivan.schemas.requirement import BuyerRequirement  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _event(text: str, **kw) -> OpenClawEvent:
    base = dict(
        source="openclaw", channel="wechat", conversation_id="smoke_conv",
        message_id="smoke_msg", sender_id="user_001", sender_display_name="Operator",
        message_text=text, role_context="user", mode="command",
    )
    base.update(kw)
    return OpenClawEvent(**base)


def _observe():
    events: list = []
    gateway.add_call_observer(events.append)
    return events


def _assert_no_external_or_mock(events, name) -> None:
    external = [e for e in events if e.external_api_called and e.ok]
    mock_fb = [e for e in events if e.configured_provider not in ("mock", "none") and e.used_provider == "mock"]
    _check(f"{name}: no external API call", not external, f"{len(external)} external calls")
    _check(f"{name}: no silent mock fallback", not mock_fb, f"{len(mock_fb)} mock fallbacks")


SAFE_ACTIONS = {
    "pending_email_approval", "pending_destination_confirmation",
    "pending_requirement_confirmation", "pending_product_confirmation",
    "pending_supplier_selection", "pending_supplier_confirmation",
    "pending_dependency_recovery", "reduced_strength_local_model_unavailable",
}


def scenario_1_normal_chinese_rfq():
    db = _session()
    events = _observe()
    try:
        result = create_rfq_from_event(
            _event("帮我询价 5000 件格子衬衫，45 天内交东京，高品质。"), db
        )
    finally:
        gateway.remove_call_observer(events.append)
    print(f"  action={result.action} provider_events={[ (e.configured_provider,e.used_provider,e.ok) for e in events]}")
    _check("S1: safe action", result.action in SAFE_ACTIONS, result.action)
    reply = result.user_control_message or ""
    _check("S1: reply is non-empty", bool(reply))
    _check("S1: no debug leakage", not any(t in reply for t in ("Strategy=", "GLTG P50", "draft_", "TBD")))
    _check("S1: no outbound before approval", not result.drafts_created or result.action == "pending_email_approval")
    _assert_no_external_or_mock(events, "S1")


def scenario_2_missing_destination():
    db = _session()

    def _unresolved(**kw):
        req = BuyerRequirement(
            raw_text=kw.get("raw_text", ""), language="zh", category="apparel",
            product_type="plaid shirt", quantity=5000, destination="", delivery_days=45,
        )
        req.extra["field_sources"] = {"product_type": "language_skill", "destination": "raw_text_only"}
        req.extra["destination_raw"] = "东京"
        return req

    orig = rfqe.structure_customer_requirement_with_llm
    rfqe.structure_customer_requirement_with_llm = _unresolved

    def _boom(*a, **k):
        raise AssertionError("GLTG must not run before destination is confirmed")

    orig_sim = rfqe.GLTGClient.simulate
    rfqe.GLTGClient.simulate = _boom
    try:
        result = create_rfq_from_event(_event("询价 5000 件格子衬衫，45天交东京"), db)
    finally:
        rfqe.structure_customer_requirement_with_llm = orig
        rfqe.GLTGClient.simulate = orig_sim
    _check("S2: pending_destination_confirmation", result.action == "pending_destination_confirmation", result.action)
    _check("S2: no drafts created", result.drafts_created == [])
    _check("S2: GLTG not run (p50=0)", result.gltg_simulation.p50_days == 0)
    _check("S2: reply asks for destination", "目的地" in (result.user_control_message or ""))


def scenario_3_supplier_count_below_three():
    from aivan.execution.safety import evaluate_supplier_readiness, supplier_action

    ok = True
    detail = ""
    try:
        zero = supplier_action([])
        one = supplier_action([{"supplier_id": "s1", "email": "a@x.com"}])
        two_feas, two_ready = evaluate_supplier_readiness(
            [{"supplier_id": "s1", "email": "a@x.com"}, {"supplier_id": "s2", "email": "b@x.com"}]
        )
        ok = (zero == "pending_supplier_selection"
              and one == "pending_supplier_confirmation"
              and two_feas == "thin" and two_ready)
        detail = f"0->{zero}, 1->{one}, 2->({two_feas},{two_ready})"
    except Exception as exc:  # must never error on <3 suppliers
        ok = False
        detail = f"raised {exc!r}"
    _check("S3: supplier count <3 handled, no error", ok, detail)


def scenario_4_local_model_failure_deterministic_fallback():
    # Point at ollama with an unreachable endpoint -> LocalModelUnavailableError
    # inside structuring -> deterministic fallback. Must NOT use mock or cloud.
    db = _session()
    saved = {k: os.environ.get(k) for k in ("AIVAN_LLM_PROVIDER", "AIVAN_LLM_API_ENABLED",
                                            "OLLAMA_BASE_URL", "AIVAN_LANGUAGE_SKILL_ENABLED")}
    os.environ.update({
        "AIVAN_LLM_PROVIDER": "ollama", "AIVAN_LLM_API_ENABLED": "true",
        "OLLAMA_BASE_URL": "http://127.0.0.1:59999",  # nothing listening
        "AIVAN_LANGUAGE_SKILL_ENABLED": "false",
    })
    gateway.reset_provider()
    events = _observe()
    try:
        result = create_rfq_from_event(_event("询价 5000 件格子衬衫，45天交东京"), db)
    finally:
        gateway.remove_call_observer(events.append)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        gateway.reset_provider()
    attempted = [e for e in events if e.configured_provider == "ollama"]
    _check("S4: local model was attempted", bool(attempted),
           f"{[(e.used_provider, e.ok) for e in events]}")
    _assert_no_external_or_mock(events, "S4")
    _check("S4: safe action after failure", result.action in SAFE_ACTIONS, result.action)


def scenario_5_production_auth_fail_closed():
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from aivan.api.main import app, get_db

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app.dependency_overrides[get_db] = lambda: _yield_db(Session)

    saved = {k: os.environ.get(k) for k in ("AIVAN_ENV", "AIVAN_API_KEY", "AIVAN_AUTH_SECRET")}
    for k in saved:
        os.environ.pop(k, None)
    os.environ["AIVAN_ENV"] = "production"
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            protected = c.get("/api/projects").status_code
            health = c.get("/health").status_code
    finally:
        app.dependency_overrides.clear()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        engine.dispose()
    _check("S5: protected route rejected in prod without secret", protected in (401, 403, 503), f"status={protected}")
    _check("S5: health open in prod", health == 200, f"status={health}")


def _yield_db(Session):
    db = Session()
    try:
        yield db
    finally:
        db.close()


def main() -> int:
    print(f"AIVAN production smoke — provider={os.environ.get('AIVAN_LLM_PROVIDER','mock')} "
          f"model={os.environ.get('OLLAMA_MODEL','-')}\n")
    scenario_1_normal_chinese_rfq()
    scenario_2_missing_destination()
    scenario_3_supplier_count_below_three()
    scenario_4_local_model_failure_deterministic_fallback()
    scenario_5_production_auth_fail_closed()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
