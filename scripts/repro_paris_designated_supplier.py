"""Reproduce the WeChat failure from IMG_9885:

Input: "询价 5000 件高品质格子衬衫，45 天内交巴黎。请向指定供应商 abcdyi 询价"
Observed on device: "⚠️ Agent couldn't generate a response. Please try again."

This runs the REAL AIVAN pipeline locally (no CTYUN). It measures:
  1. How many llm_complete_json calls the pipeline makes for this input.
  2. Total wall time if the local model is *slow/unhealthy* (simulated).
  3. Whether the backend still returns a usable reply_text through /invoke.
  4. Whether "designated supplier abcdyi" changes routing / draft count.
"""
from __future__ import annotations
import os
import time

DB_PATH = "/tmp/aivan_repro_paris.sqlite3"
os.environ.update({
    "AIVAN_ENV": "local",
    "AIVAN_DB_URL": f"sqlite:///{DB_PATH}",
    "AIVAN_LLM_PROVIDER": "ollama",
    "OLLAMA_MODEL": "qwen3.5:2b",
    "OLLAMA_BASE_URL": "http://127.0.0.1:59999",
    "AIVAN_EXTERNAL_MODEL_API_ENABLED": "false",
    "AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED": "false",
    "AIVAN_VLM_API_ENABLED": "false",
    "AIVAN_LANGUAGE_SKILL_ENABLED": "true",
    "AIVAN_LANGUAGE_SKILL_BASE_URL": "http://127.0.0.1:8788",
    "AIVAN_ALLOW_STUB_SUPPLIERS": "false",
    "OPENCLAW_MOCK_MODE": "true",
    "AIVAN_TEST_MODE": "true",
    "AIVAN_TEST_TENANT_ID": "repro_tenant",
    "AIVAN_EMAIL_SEND_MODE": "simulation",
})
try:
    os.remove(DB_PATH)
except OSError:
    pass

import httpx  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from aivan.db.models import Base  # noqa: E402
from aivan.db.repositories.supplier_repo import SupplierRepository  # noqa: E402
from aivan.integrations.language_skill_client import set_default_transport as ls_set_transport  # noqa: E402
from aivan.integrations import gltg_client as gltg_client_mod  # noqa: E402
from aivan.llm import gateway  # noqa: E402
from tests.gltg_fake import mock_transport as gltg_mock_transport  # noqa: E402

RFQ_ZH = "询价 5000 件高品质格子衬衫，45 天内交巴黎。请向指定供应商 abcdyi 询价"

_NORMALIZE = {
    "raw_text": RFQ_ZH,
    "language": {"detected": "zh", "confidence": 0.99},
    "canonical_language": "en",
    "canonical_text": "RFQ: 5000 pcs high quality plaid shirts, deliver to Paris within 45 days; "
                      "please quote from designated supplier abcdyi.",
    "requested_output_language": "zh",
    "final_output_language": "zh",
    "field_evidence": {
        "quantity": {"raw": "5000 件", "value": 5000},
        "product_name": {"raw": "格子衬衫", "value": "plaid shirt"},
        "quality_level": {"raw": "高品质", "value": "high"},
        "destination": {"raw": "交巴黎", "value": "Paris"},
        "lead_time_days": {"raw": "45 天", "value": 45},
        "designated_supplier": {"raw": "指定供应商 abcdyi", "value": "abcdyi"},
    },
    "warnings": [],
}
_STRUCTURE = {
    "schema": "trade_rfq.v1",
    "validation_status": "valid",
    "structured": {
        "quantity": 5000,
        "quantity_unit": "pcs",
        "product_name": "plaid shirt",
        "product_category": "apparel",
        "product_modifier": ["plaid"],
        "quality_level": "high",
        "destination": "Paris",
        "lead_time_days": 45,
        "intent": "supplier_rfq",
        "designated_supplier": "abcdyi",
    },
    "missing_fields": [],
    "confidence_score": 0.96,
    "field_sources": {k: "language_skill" for k in
                      ("quantity", "product_name", "destination", "lead_time_days", "quality_level")},
}


def _ls_handler(captured: dict):
    def handle(request: httpx.Request) -> httpx.Response:
        captured.setdefault("paths", []).append(request.url.path)
        if request.url.path == "/v1/inbound/normalize":
            return httpx.Response(200, json=_NORMALIZE)
        if request.url.path == "/v1/structure/rfq":
            return httpx.Response(200, json=_STRUCTURE)
        return httpx.Response(404, json={"detail": "not found"})
    return handle


def _seed(session):
    repo = SupplierRepository(session)
    for i in range(1, 6):
        sid = f"sup_{i:03d}"
        repo.upsert(sid, {
            "name": f"Shirt Maker {i}",
            "company_type": "factory",
            "categories_json": ["apparel"],
            "capabilities_json": ["plaid shirts", "woven garments"],
            "materials_json": ["100% cotton"],
            "moq_min": 1000,
            "daily_capacity": 800,
            "region": "China",
            "country": "CN",
            "languages_json": ["zh", "en"],
            "channels_json": ["email"],
            "email": f"{sid}@apparel.example",
            "incoterms_json": ["FOB", "DDP"],
            "logistics_modes_json": ["air", "sea"],
            "quality_score": 0.9,
            "past_performance_score": 0.9,
            "risk_tags_json": [],
            "active": True,
        })
    session.commit()


# ── Instrument llm_complete_json: count calls, simulate SLOW unhealthy model ──
LLM_SLEEP = float(os.environ.get("REPRO_LLM_SLEEP", "0"))
calls: list[str] = []
_orig = gateway.llm_complete_json


def _patched(task, system_prompt, user_prompt, schema_hint=None, *a, **k):
    calls.append(task)
    if LLM_SLEEP:
        time.sleep(LLM_SLEEP)
    return _orig(task, system_prompt, user_prompt, schema_hint, *a, **k)


gateway.llm_complete_json = _patched
# Patch the already-imported references in rfq_execution / requirement_agent.
import aivan.execution.rfq_execution as rexec  # noqa: E402
import aivan.agents.requirement_agent as ragent  # noqa: E402
rexec.llm_complete_json = _patched
ragent.llm_complete_json = _patched


def main():
    engine = create_engine(os.environ["AIVAN_DB_URL"])
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    _seed(session)

    from aivan.sourcing.supplier_registry import clear_registry, load_from_db
    clear_registry()
    load_from_db(session)

    captured: dict = {}
    ls_set_transport(httpx.MockTransport(_ls_handler(captured)))
    gltg_client_mod.set_default_transport(gltg_mock_transport())

    from aivan.openclaw.event_adapter import parse_openclaw_event
    from aivan.execution.rfq_execution import create_rfq_from_event

    event = parse_openclaw_event({
        "source": "wechat",
        "channel": "wechat",
        "conversation_id": "repro-paris-1",
        "sender_id": "wechat-user",
        "message_text": RFQ_ZH,
        "message_type": "text",
        "mode": "auto",
    })

    t0 = time.time()
    error = None
    try:
        result = create_rfq_from_event(event, session)
    except Exception as exc:  # noqa: BLE001
        import traceback
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        result = None
    elapsed = time.time() - t0

    print("=" * 70)
    print(f"RFQ input   : {RFQ_ZH}")
    print(f"LS paths    : {captured.get('paths')}")
    print(f"LLM calls   : {len(calls)} -> {calls}")
    print(f"Per-call sim: {LLM_SLEEP}s  =>  est real slow-model wall time = "
          f"{len(calls) * (LLM_SLEEP or 30):.0f}s at 30s timeout each")
    print(f"Elapsed     : {elapsed:.2f}s")
    if error:
        print("ERROR (pipeline raised):")
        print(error)
    else:
        data = result.model_dump()
        reply = (data.get("reply_text") or data.get("user_control_message")
                 or data.get("message") or "")
        print(f"action      : {data.get('action')}")
        print(f"project_id  : {data.get('project_id')}")
        print(f"drafts      : {len(data.get('drafts') or [])}")
        print(f"reply_text  : {reply[:400]!r}")
        print(f"reply EMPTY?: {not bool((reply or '').strip())}")
    print("=" * 70)

    ls_set_transport(None)
    gltg_client_mod.set_default_transport(None)
    session.close()


if __name__ == "__main__":
    main()
