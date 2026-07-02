from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import GiraffeContext
from aivan.sourcing.supplier_models import SupplierProfile
from aivan.utils.tenant import resolve_service_tenant_id

# Demo stub suppliers live in data/demo (never in production src) and load only
# when explicitly enabled. Production must not fabricate supplier candidates.
_STUB_SUPPLIERS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "demo" / "stub_suppliers.json"
)


def stub_suppliers_allowed() -> bool:
    """Whether demo stub suppliers may be used.

    Never in production. Otherwise honor ``AIVAN_ALLOW_STUB_SUPPLIERS`` when set;
    default to allowed in local/dev so offline flows keep working.
    """
    if os.environ.get("AIVAN_ENV", "local").strip().lower() == "production":
        return False
    raw = os.environ.get("AIVAN_ALLOW_STUB_SUPPLIERS")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _load_stub_supplier_data() -> tuple[dict, ...]:
    try:
        with open(_STUB_SUPPLIERS_PATH, encoding="utf-8") as fh:
            return tuple(json.load(fh))
    except (OSError, ValueError):
        return ()


def _default_known_suppliers() -> list[SupplierProfile]:
    if not stub_suppliers_allowed():
        return []
    return [SupplierProfile(**dict(record)) for record in _load_stub_supplier_data()]


class GiraffeDBClient:
    """Replaceable private-domain business-memory facade.

    The methods intentionally mirror the PRD's Giraffe DB lookup surface. Until
    the real Giraffe DB service is available, this facade combines repository
    data with deterministic stub records so orchestration code has a stable
    integration boundary.
    """

    def __init__(self, db: Session):
        self.db = db

    def build_context(
        self,
        requirement: BuyerRequirement,
        customer_id: str = "",
        user_id: str = "",
    ) -> GiraffeContext:
        suppliers = self.query_suppliers(requirement)
        return GiraffeContext(
            customers=self.query_customers(customer_id),
            customer_preferences=self.query_customer_preferences(customer_id),
            suppliers=[s.model_dump() for s in suppliers],
            supplier_relationships=self.query_supplier_relationships(suppliers),
            historical_rfqs=self.query_historical_rfqs(customer_id, requirement),
            historical_quotations=self.query_historical_quotations(requirement),
            historical_lead_time_records=self.query_historical_lead_time_records(requirement),
            product_categories=self.query_product_categories(requirement),
            user_preferences=self.query_user_preferences(user_id),
            approval_history=self.query_approval_history(user_id),
            draft_revision_history=self.query_draft_revision_history(user_id),
            risk_flags=self.query_risk_flags(suppliers),
        )

    def query_customers(self, customer_id: str) -> list[dict]:
        if not customer_id:
            return []
        return [{"customer_id": customer_id, "relationship": "known_or_pending"}]

    def query_customer_preferences(self, customer_id: str) -> list[dict]:
        if not customer_id:
            return []
        return [{"customer_id": customer_id, "preference": "speed_sensitive_when_marked_urgent"}]

    def query_suppliers(self, requirement: BuyerRequirement) -> list[SupplierProfile]:
        from aivan.sourcing.supplier_registry import list_active

        registry_suppliers = list_active()
        category = (requirement.category or "").lower()
        material = (requirement.fabric_material or requirement.material_spec or "").lower()
        candidates = []
        for supplier in registry_suppliers:
            category_fit = not category or category in [c.lower() for c in supplier.categories]
            material_fit = not material or any(m.lower() in material or material in m.lower() for m in supplier.materials)
            if category_fit or material_fit:
                candidates.append(supplier)
        return candidates or _default_known_suppliers()

    def query_supplier_relationships(self, suppliers: list[SupplierProfile]) -> list[dict]:
        return [
            {
                "supplier_id": supplier.supplier_id,
                "relationship": "known",
                "reliability_score": supplier.past_performance_score or supplier.delivery_score,
            }
            for supplier in suppliers
        ]

    def query_historical_rfqs(self, customer_id: str, requirement: BuyerRequirement) -> list[dict]:
        return [
            {
                "customer_id": customer_id,
                "category": requirement.category,
                "note": "stubbed historical RFQ lookup",
            }
        ]

    def query_historical_quotations(self, requirement: BuyerRequirement) -> list[dict]:
        return [{"category": requirement.category, "currency": "USD", "note": "stubbed quotation history"}]

    def query_historical_lead_time_records(self, requirement: BuyerRequirement) -> list[dict]:
        return [{"category": requirement.category, "destination": requirement.destination, "note": "stubbed lead-time history"}]

    def query_product_categories(self, requirement: BuyerRequirement) -> list[dict]:
        return [{"category": requirement.category or "general", "source": "requirement"}]

    def query_user_preferences(self, user_id: str) -> list[dict]:
        if not user_id:
            return [{"user_id": "default", "preference": "require_email_approval_for_counterparty_messages"}]
        from aivan.db.repositories.preference_repo import UserPreferenceRepository

        records = UserPreferenceRepository(self.db).list_for_user(user_id)
        if records:
            return [
                {
                    "user_id": record.user_id,
                    "preference_type": record.preference_type,
                    "value": record.value_json,
                    "source": record.source,
                    "confidence": record.confidence,
                }
                for record in records
            ]
        return [{"user_id": user_id, "preference": "require_email_approval_for_counterparty_messages"}]

    def query_approval_history(self, user_id: str) -> list[dict]:
        return [{"user_id": user_id or "default", "approved_channel": "email"}]

    def query_draft_revision_history(self, user_id: str) -> list[dict]:
        return [{"user_id": user_id or "default", "note": "stubbed draft revision history"}]

    def query_risk_flags(self, suppliers: list[SupplierProfile]) -> list[dict]:
        flags = []
        for supplier in suppliers:
            for tag in supplier.risk_tags:
                flags.append({"supplier_id": supplier.supplier_id, "risk_flag": tag})
        return flags


def _giraffe_db_service_headers(tenant_id: str, idempotency_key: str = "") -> dict[str, str]:
    headers = {"X-Service-Tenant-ID": tenant_id}
    service_auth = os.environ.get("GIRAFFE_DB_SERVICE_AUTH_SECRET")
    if service_auth:
        headers["X-Service-Auth"] = service_auth
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def build_graph_trace_metadata(event, project_id: str) -> dict:
    """Deterministic trace + idempotency metadata for giraffe-db graph payloads.

    A stable ``source_trace_id`` / ``idempotency_key`` lets giraffe-db deduplicate
    if the multi-POST persistence is retried, instead of leaving partial duplicate
    graph records.
    """
    message_ref = getattr(event, "message_id", None) or getattr(event, "conversation_id", None) or "unknown"
    source_event_id = getattr(event, "message_id", None) or ""
    trace_id = f"aivan:{project_id}:{message_ref}"
    return {
        "source_system": "aivan",
        "source_trace_id": trace_id,
        "source_event_id": source_event_id,
        "aivan_project_id": project_id,
        "idempotency_key": trace_id,
    }


def persist_rfq_gltg_graph(*, event, project_id: str, requirement, strategy, gltg) -> dict:
    """Persist a pre-PO RFQ/GLTG decision graph to giraffe-db over HTTP.

    Disabled by default so local unit tests and offline development keep using the
    existing in-process facade. Server E2E enables this with
    AIVAN_PERSIST_GIRAFFE_DB_GRAPH=true.
    """
    import httpx

    if os.environ.get("AIVAN_PERSIST_GIRAFFE_DB_GRAPH", "false").lower() != "true":
        return {}
    base_url = os.environ.get("GIRAFFE_DB_BASE_URL", "").rstrip("/")
    if not base_url:
        return {}

    tenant_id = resolve_service_tenant_id()
    trace = build_graph_trace_metadata(event, project_id)
    headers = _giraffe_db_service_headers(tenant_id, idempotency_key=trace["idempotency_key"])
    timeout = float(os.environ.get("GIRAFFE_DB_TIMEOUT_SECONDS", "10"))

    def post(client: httpx.Client, path: str, payload: dict) -> dict:
        # Every payload carries the same trace/idempotency metadata so giraffe-db
        # can deduplicate a retried multi-step persistence.
        enriched = {**payload, **trace}
        response = client.post(f"{base_url}{path}", json=enriched, headers=headers)
        response.raise_for_status()
        return response.json()

    buyer_name = event.sender_display_name or event.sender_id or "AIVAN Buyer"
    requirement_payload = requirement.model_dump() if hasattr(requirement, "model_dump") else dict(requirement or {})
    strategy_payload = strategy.model_dump() if hasattr(strategy, "model_dump") else dict(strategy or {})
    gltg_payload = gltg.model_dump() if hasattr(gltg, "model_dump") else dict(gltg or {})

    with httpx.Client(timeout=timeout) as client:
        buyer = post(client, "/api/data/buyers", {"buyer_name": buyer_name, "metadata_json": {"aivan_sender_id": event.sender_id}})
        buyer_id = buyer["buyer_id"]
        case = post(
            client,
            "/api/data/procurement-cases",
            {
                "buyer_id": buyer_id,
                "source_channel": event.channel,
                "source_conversation_id": event.conversation_id,
                "source_event_id": event.message_id or None,
                "status": "open",
                "metadata_json": {"aivan_project_id": project_id, "requirement": requirement_payload},
            },
        )
        procurement_case_id = case["procurement_case_id"]
        rfq = post(
            client,
            "/api/data/rfqs",
            {
                "procurement_case_id": procurement_case_id,
                "buyer_id": buyer_id,
                "title": f"AIVAN RFQ {project_id}",
                "status": "draft_pending_approval",
                "metadata_json": {"aivan_project_id": project_id, "requirement": requirement_payload, "strategy": strategy_payload},
            },
        )
        rfq_id = rfq["id"]
        gltg_run = post(
            client,
            "/api/data/gltg-simulation-runs",
            {
                "procurement_case_id": procurement_case_id,
                "rfq_id": rfq_id,
                "buyer_id": buyer_id,
                "final_p50_days": gltg_payload.get("p50_days"),
                "final_p80_days": gltg_payload.get("p80_days"),
                "final_p90_days": gltg_payload.get("p90_days"),
                "deadline_risk_level": gltg_payload.get("deadline_risk_level"),
                "output_json": gltg_payload,
                "explanation_json": {
                    "source": "aivan",
                    "source_api_version": gltg_payload.get("source_api_version"),
                    "gltg_service_run_id": gltg_payload.get("gltg_run_id"),
                    "assessment_packet": gltg_payload.get("assessment_packet") or {},
                },
            },
        )
        gltg_run_id = gltg_run["gltg_run_id"]
        pricing = post(
            client,
            "/api/data/pricing-decision-inputs",
            {
                "procurement_case_id": procurement_case_id,
                "rfq_id": rfq_id,
                "buyer_id": buyer_id,
                "gltg_run_id": gltg_run_id,
                "input_json": {"source": "aivan", "strategy": strategy_payload},
                "manual_review_required": True,
                "explanation_json": {"source": "aivan", "reason": "pre-PO RFQ pending human approval"},
            },
        )
        pricing_input_id = pricing["pricing_input_id"]
        decision = post(
            client,
            "/api/data/case-decision-options",
            {
                "procurement_case_id": procurement_case_id,
                "rfq_id": rfq_id,
                "buyer_id": buyer_id,
                "option_label": "known_suppliers_first",
                "option_type": strategy_payload.get("supplier_scope", "known_suppliers_first"),
                "gltg_run_ids_json": [gltg_run_id],
                "pricing_input_ids_json": [pricing_input_id],
                "estimated_lead_time_days": gltg_payload.get("selected_confidence_days"),
                "p50_days": gltg_payload.get("p50_days"),
                "p80_days": gltg_payload.get("p80_days"),
                "p90_days": gltg_payload.get("p90_days"),
                "deadline_risk_level": gltg_payload.get("deadline_risk_level"),
                "recommendation_score": 0.7,
                "recommendation_reason_json": {"source": "aivan", "human_approval_required": True},
                "tradeoff_summary_json": {"gltg": gltg_payload},
                "status": "draft",
            },
        )
        comparison = post(
            client,
            "/api/data/quote-comparison-snapshots",
            {
                "procurement_case_id": procurement_case_id,
                "rfq_id": rfq_id,
                "buyer_id": buyer_id,
                "snapshot_type": "pre_po_gltg_decision",
                "gltg_run_ids_json": [gltg_run_id],
                "pricing_input_ids_json": [pricing_input_id],
                "comparison_json": {"source": "aivan", "gltg": gltg_payload},
                "ranking_json": {"top_decision_option_id": decision["decision_option_id"]},
            },
        )

    return {
        "tenant_id": tenant_id,
        "source_trace_id": trace["source_trace_id"],
        "idempotency_key": trace["idempotency_key"],
        "procurement_case_id": procurement_case_id,
        "rfq_id": rfq_id,
        "gltg_run_id": gltg_run_id,
        "pricing_input_id": pricing_input_id,
        "decision_option_id": decision["decision_option_id"],
        "comparison_snapshot_id": comparison["comparison_snapshot_id"],
    }
