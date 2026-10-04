from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from sqlalchemy.orm import Session

from aivan.schemas.requirement import BuyerRequirement
from aivan.utils.env import env_bool
from aivan.schemas.rfq import GiraffeContext
from aivan.sourcing.supplier_models import SupplierProfile
from aivan.utils.tenant import resolve_service_tenant, resolve_tenant

# Demo stub suppliers live in data/demo (never in production src) and load only
# when explicitly enabled. Production must not fabricate supplier candidates.
_STUB_SUPPLIERS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "demo" / "stub_suppliers.json"
)


class GiraffeDBContextError(RuntimeError):
    """Stable, non-sensitive failure raised by the private-data context client."""


def stub_suppliers_allowed() -> bool:
    """Whether demo stub suppliers may be used.

    Never in production. Otherwise honor ``AIVAN_ALLOW_STUB_SUPPLIERS`` when set;
    default to allowed in local/dev so offline flows keep working.
    """
    if os.environ.get("AIVAN_ENV", "local").strip().lower() == "production":
        return False
    return env_bool("AIVAN_ALLOW_STUB_SUPPLIERS", default=True)


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
    """Tenant-bound private-domain context client.

    A configured ``GIRAFFE_DB_BASE_URL`` selects the real HTTP Data API. In
    production that endpoint is mandatory and local registries/demo records are
    never consulted. Local development keeps the explicit demo boundary for
    offline tests only.
    """

    def __init__(self, db: Session, *, tenant_id: str | None = None):
        self.db = db
        self.tenant_id = tenant_id or resolve_service_tenant(context="giraffe_db_client")
        self.base_url = os.environ.get("GIRAFFE_DB_BASE_URL", "").strip().rstrip("/")
        self.timeout = float(os.environ.get("GIRAFFE_DB_TIMEOUT_SECONDS", "10"))

    @property
    def uses_remote_data_api(self) -> bool:
        return bool(self.base_url)

    def _validate_context_configuration(self) -> None:
        production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
        if production and not self.uses_remote_data_api:
            raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_ENDPOINT_REQUIRED")
        if self.uses_remote_data_api and not os.environ.get("GIRAFFE_DB_SERVICE_AUTH_SECRET", "").strip():
            raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_AUTH_REQUIRED")

    def _remote_get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        self._validate_context_configuration()
        headers = _giraffe_db_service_headers(self.tenant_id)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.get(f"{self.base_url}{path}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_UNAVAILABLE") from exc
        if response.status_code != 200:
            raise GiraffeDBContextError(f"GIRAFFE_DB_CONTEXT_HTTP_{response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_INVALID_RESPONSE") from exc

    def build_context(
        self,
        requirement: BuyerRequirement,
        customer_id: str = "",
        user_id: str = "",
    ) -> GiraffeContext:
        self._validate_context_configuration()
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
        if self.uses_remote_data_api:
            # The current caller's customer identifier is not guaranteed to be
            # a giraffe-db buyer_id. Do not invent or cross-map an identity.
            return []
        if not customer_id:
            return []
        return [{"customer_id": customer_id, "relationship": "known_or_pending"}]

    def query_customer_preferences(self, customer_id: str) -> list[dict]:
        if self.uses_remote_data_api:
            return []
        if not customer_id:
            return []
        return [{"customer_id": customer_id, "preference": "speed_sensitive_when_marked_urgent"}]

    def query_suppliers(self, requirement: BuyerRequirement) -> list[SupplierProfile]:
        if self.uses_remote_data_api:
            return _filter_supplier_profiles(self._all_remote_suppliers(), requirement)

        from aivan.sourcing.supplier_registry import list_active

        registry_suppliers = list_active(tenant_id=self.tenant_id)
        candidates = _filter_supplier_profiles(registry_suppliers, requirement)
        return candidates or _filter_supplier_profiles(_default_known_suppliers(), requirement)

    def _all_remote_suppliers(self) -> list[SupplierProfile]:
        """Read the complete tenant catalog, or fail without partial candidates."""
        suppliers: list[SupplierProfile] = []
        seen_ids: set[str] = set()
        offset = 0
        expected_total: int | None = None
        while True:
            payload = self._remote_get(
                "/api/data/suppliers",
                params={"active": "true", "limit": 100, "offset": offset},
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_INVALID_RESPONSE")
            total, limit, page_offset = (payload.get(key) for key in ("total", "limit", "offset"))
            if (
                type(total) is not int or type(limit) is not int or type(page_offset) is not int
            ):
                raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_INVALID_RESPONSE")
            if (
                total < 0 or limit <= 0 or page_offset != offset
                or len(payload["items"]) > limit
                or offset + len(payload["items"]) > total
                or (expected_total is not None and total != expected_total)
                or (not payload["items"] and offset < total)
            ):
                raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_INVALID_RESPONSE")
            expected_total = total
            for record in payload["items"]:
                if not isinstance(record, dict):
                    raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_INVALID_RESPONSE")
                record_tenant = record.get("tenant_id")
                if record_tenant != self.tenant_id:
                    raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_TENANT_MISMATCH")
                supplier_id = record.get("supplier_id")
                if not isinstance(supplier_id, str) or not supplier_id or supplier_id in seen_ids:
                    raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_INVALID_RESPONSE")
                seen_ids.add(supplier_id)
                suppliers.append(_supplier_profile_from_data_api(record))
            offset += len(payload["items"])
            if offset == total:
                return suppliers

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
        if self.uses_remote_data_api:
            return []
        return [
            {
                "customer_id": customer_id,
                "category": requirement.category,
                "note": "stubbed historical RFQ lookup",
            }
        ]

    def query_historical_quotations(self, requirement: BuyerRequirement) -> list[dict]:
        if self.uses_remote_data_api:
            return []
        return [{"category": requirement.category, "currency": "USD", "note": "stubbed quotation history"}]

    def query_historical_lead_time_records(self, requirement: BuyerRequirement) -> list[dict]:
        if self.uses_remote_data_api:
            return []
        return [{"category": requirement.category, "destination": requirement.destination, "note": "stubbed lead-time history"}]

    def query_product_categories(self, requirement: BuyerRequirement) -> list[dict]:
        if self.uses_remote_data_api:
            return []
        return [{"category": requirement.category or "general", "source": "requirement"}]

    def query_user_preferences(self, user_id: str) -> list[dict]:
        if self.uses_remote_data_api:
            # No accepted giraffe-db user-preference endpoint exists yet.
            # Empty is truthful; a local default must not masquerade as a
            # private-domain fact in production.
            return []
        if not user_id:
            return [{"user_id": "default", "preference": "require_email_approval_for_counterparty_messages"}]
        from aivan.db.repositories.preference_repo import UserPreferenceRepository

        records = UserPreferenceRepository(self.db).list_for_user(user_id, tenant_id=self.tenant_id)
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
        if self.uses_remote_data_api:
            return []
        return [{"user_id": user_id or "default", "approved_channel": "email"}]

    def query_draft_revision_history(self, user_id: str) -> list[dict]:
        if self.uses_remote_data_api:
            return []
        return [{"user_id": user_id or "default", "note": "stubbed draft revision history"}]

    def query_risk_flags(self, suppliers: list[SupplierProfile]) -> list[dict]:
        flags = []
        for supplier in suppliers:
            for tag in supplier.risk_tags:
                flags.append({"supplier_id": supplier.supplier_id, "risk_flag": tag})
        return flags


def _filter_supplier_profiles(
    suppliers: list[SupplierProfile], requirement: BuyerRequirement
) -> list[SupplierProfile]:
    category = (requirement.category or "").strip().lower()
    material = (requirement.fabric_material or requirement.material_spec or "").strip().lower()
    candidates: list[SupplierProfile] = []
    for supplier in suppliers:
        category_fit = bool(category) and category in [item.lower() for item in supplier.categories]
        material_fit = bool(material) and any(
            item.strip() and (item.strip().lower() in material or material in item.strip().lower())
            for item in supplier.materials
        )
        if not (category or material) or category_fit or material_fit:
            candidates.append(supplier)
    return candidates


def _supplier_profile_from_data_api(record: dict[str, Any]) -> SupplierProfile:
    """Map only fields published by giraffe-db's structured supplier API."""

    raw_metadata = record.get("metadata_json")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    return SupplierProfile(
        supplier_id=str(record.get("supplier_id") or ""),
        name=str(record.get("supplier_name") or record.get("name_en") or ""),
        company_type=str(record.get("company_type") or ""),
        categories=list(record.get("categories_json") or []),
        capabilities=list(record.get("capabilities_json") or []),
        materials=list(record.get("materials_json") or []),
        moq_min=int(metadata.get("moq_min") or 0),
        moq_max=int(metadata.get("moq_max") or 0),
        daily_capacity=int(metadata.get("daily_capacity") or 0),
        monthly_capacity=int(metadata.get("monthly_capacity") or 0),
        region=str(record.get("region") or ""),
        country=str(record.get("country") or ""),
        languages=list(record.get("languages_json") or []),
        channels=list(record.get("channels_json") or []),
        email=str(record.get("email") or ""),
        openclaw_peer_id=str(record.get("openclaw_peer_id") or ""),
        payment_terms=str(record.get("payment_terms") or ""),
        incoterms_supported=list(record.get("incoterms_json") or []),
        logistics_modes=list(record.get("logistics_modes_json") or []),
        quality_score=float(record.get("quality_score") or 0.0),
        delivery_score=float(record.get("delivery_score") or 0.0),
        price_score=float(record.get("price_score") or 0.0),
        past_performance_score=float(record.get("past_performance_score") or 0.0),
        risk_tags=list(record.get("risk_tags_json") or []),
        notes=str(record.get("notes") or ""),
        active=bool(record.get("active", True)),
    )


def _giraffe_db_service_headers(tenant_id: str, idempotency_key: str = "") -> dict[str, str]:
    headers = {"X-Service-Tenant-ID": tenant_id}
    service_auth = os.environ.get("GIRAFFE_DB_SERVICE_AUTH_SECRET")
    if service_auth:
        headers["X-Service-Auth"] = service_auth
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def build_graph_trace_metadata(event, project_id: str) -> dict:
    """Build deterministic consumer trace and operation-key roots.

    The keys make retries identifiable. Provider-side deduplication is a
    separate giraffe-db capability and must not be inferred from these values.
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

    persistence_enabled = (
        os.environ.get("AIVAN_PERSIST_GIRAFFE_DB_GRAPH", "false").lower() == "true"
    )
    production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    if production and not persistence_enabled:
        raise RuntimeError("GIRAFFE_DB_GRAPH_PERSISTENCE_REQUIRED")
    if not persistence_enabled:
        return {}
    base_url = os.environ.get("GIRAFFE_DB_BASE_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError(
            "GIRAFFE_DB_BASE_URL_REQUIRED_FOR_GRAPH_PERSISTENCE"
        )

    # Fail closed: never stamp giraffe-db business facts under a guessed tenant.
    event_tenant = getattr(event, "tenant_id", None)
    tenant_id = (
        resolve_tenant(explicit=event_tenant, context="giraffe_db_rfq_graph_write")
        if event_tenant else resolve_service_tenant(context="giraffe_db_rfq_graph_write")
    )
    trace = build_graph_trace_metadata(event, project_id)
    timeout = float(os.environ.get("GIRAFFE_DB_TIMEOUT_SECONDS", "10"))

    def post(client: httpx.Client, step: str, path: str, payload: dict) -> dict:
        # A graph retry keeps a stable key per operation, while distinct writes
        # never share one key and therefore cannot collapse into each other.
        operation_key = f'{trace["idempotency_key"]}:{step}'
        enriched = {**payload, **trace, "idempotency_key": operation_key}
        headers = _giraffe_db_service_headers(tenant_id, idempotency_key=operation_key)
        try:
            response = client.post(f"{base_url}{path}", json=enriched, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"GIRAFFE_DB_GRAPH_INDETERMINATE_COMMIT:{step}") from exc
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise RuntimeError(f"GIRAFFE_DB_GRAPH_INDETERMINATE_COMMIT:{step}")
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(f"GIRAFFE_DB_GRAPH_INVALID_RESPONSE:{step}") from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"GIRAFFE_DB_GRAPH_INVALID_RESPONSE:{step}")
        return result

    def readback(client: httpx.Client, procurement_case_id: str) -> dict:
        headers = _giraffe_db_service_headers(tenant_id)
        try:
            response = client.get(
                f"{base_url}/api/data/procurement-cases/{procurement_case_id}/transaction-graph",
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("GIRAFFE_DB_GRAPH_READBACK_UNAVAILABLE") from exc
        if response.status_code != 200:
            raise RuntimeError("GIRAFFE_DB_GRAPH_READBACK_FAILED")
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("GIRAFFE_DB_GRAPH_READBACK_INVALID") from exc
        if not isinstance(result, dict):
            raise RuntimeError("GIRAFFE_DB_GRAPH_READBACK_INVALID")
        return result

    buyer_name = event.sender_display_name or event.sender_id or "AIVAN Buyer"
    requirement_payload = requirement.model_dump() if hasattr(requirement, "model_dump") else dict(requirement or {})
    strategy_payload = strategy.model_dump() if hasattr(strategy, "model_dump") else dict(strategy or {})
    gltg_payload = gltg.model_dump() if hasattr(gltg, "model_dump") else dict(gltg or {})
    lineage = {
        "source_system": trace["source_system"],
        "source_trace_id": trace["source_trace_id"],
        "source_event_id": trace["source_event_id"],
        "aivan_project_id": trace["aivan_project_id"],
    }

    with httpx.Client(timeout=timeout) as client:
        buyer = post(
            client,
            "buyer",
            "/api/data/buyers",
            {"buyer_name": buyer_name, "metadata_json": {"aivan_sender_id": event.sender_id, **lineage}},
        )
        buyer_id = buyer["buyer_id"]
        case = post(
            client,
            "procurement-case",
            "/api/data/procurement-cases",
            {
                "buyer_id": buyer_id,
                "source_channel": event.channel,
                "source_conversation_id": event.conversation_id,
                "source_event_id": event.message_id or None,
                "status": "open",
                "metadata_json": {**lineage, "requirement": requirement_payload},
            },
        )
        procurement_case_id = case["procurement_case_id"]
        rfq = post(
            client,
            "rfq",
            "/api/data/rfqs",
            {
                "procurement_case_id": procurement_case_id,
                "buyer_id": buyer_id,
                "title": f"AIVAN RFQ {project_id}",
                "status": "draft_pending_approval",
                "metadata_json": {**lineage, "requirement": requirement_payload, "strategy": strategy_payload},
            },
        )
        rfq_id = rfq["id"]
        gltg_run = post(
            client,
            "gltg-run",
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
                    **lineage,
                    "source_api_version": gltg_payload.get("source_api_version"),
                    "gltg_service_run_id": gltg_payload.get("gltg_run_id"),
                    "assessment_packet": gltg_payload.get("assessment_packet") or {},
                },
            },
        )
        gltg_run_id = gltg_run["gltg_run_id"]
        pricing = post(
            client,
            "pricing-input",
            "/api/data/pricing-decision-inputs",
            {
                "procurement_case_id": procurement_case_id,
                "rfq_id": rfq_id,
                "buyer_id": buyer_id,
                "gltg_run_id": gltg_run_id,
                "input_json": {"source": "aivan", "strategy": strategy_payload},
                "manual_review_required": True,
                "explanation_json": {**lineage, "reason": "pre-PO RFQ pending human approval"},
            },
        )
        pricing_input_id = pricing["pricing_input_id"]
        decision = post(
            client,
            "decision-option",
            "/api/data/case-decision-options",
            {
                "procurement_case_id": procurement_case_id,
                "rfq_id": rfq_id,
                "buyer_id": buyer_id,
                "option_label": "known_suppliers_first",
                "option_type": strategy_payload.get("supplier_scope", "known_suppliers_first"),
                "gltg_run_ids_json": [gltg_run_id],
                "pricing_input_ids_json": [pricing_input_id],
                # giraffe-db currently types estimated_lead_time_days as an
                # integer. Do not truncate the canonical fractional result;
                # persist exact quantiles in the decimal p50/p80/p90 fields.
                "p50_days": gltg_payload.get("p50_days"),
                "p80_days": gltg_payload.get("p80_days"),
                "p90_days": gltg_payload.get("p90_days"),
                "deadline_risk_level": gltg_payload.get("deadline_risk_level"),
                "recommendation_score": 0.7,
                "recommendation_reason_json": {"source": "aivan", "human_approval_required": True},
                "tradeoff_summary_json": {"gltg": gltg_payload},
                "status": "draft",
                "metadata_json": lineage,
            },
        )
        comparison = post(
            client,
            "comparison-snapshot",
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
                "metadata_json": lineage,
            },
        )
        graph = readback(client, procurement_case_id)

    expected_readback = {
        "procurement_case": ("procurement_case_id", procurement_case_id),
        "rfqs": ("id", rfq_id),
        "gltg_runs": ("gltg_run_id", gltg_run_id),
        "pricing_inputs": ("pricing_input_id", pricing_input_id),
        "decision_options": ("decision_option_id", decision["decision_option_id"]),
        "comparison_snapshots": ("comparison_snapshot_id", comparison["comparison_snapshot_id"]),
    }
    for section, (identity_field, expected_identity) in expected_readback.items():
        records = graph.get(section)
        if section == "procurement_case":
            matched = isinstance(records, dict) and records.get(identity_field) == expected_identity
        else:
            matched = isinstance(records, list) and any(
                isinstance(record, dict) and record.get(identity_field) == expected_identity
                for record in records
            )
        if not matched:
            raise RuntimeError(f"GIRAFFE_DB_GRAPH_READBACK_MISMATCH:{section}")

    lineage_fields = {
        "procurement_case": "metadata_json",
        "rfqs": "metadata_json",
        "gltg_runs": "explanation_json",
        "pricing_inputs": "explanation_json",
        "decision_options": "metadata_json",
        "comparison_snapshots": "metadata_json",
    }
    for section, lineage_field in lineage_fields.items():
        records = graph[section]
        records = [records] if isinstance(records, dict) else records
        matching_lineage = any(
            isinstance(record, dict)
            and isinstance(record.get(lineage_field), dict)
            and record[lineage_field].get("source_trace_id") == trace["source_trace_id"]
            for record in records
        )
        if not matching_lineage:
            raise RuntimeError(f"GIRAFFE_DB_GRAPH_READBACK_LINEAGE_MISMATCH:{section}")

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
        "readback_verified": True,
    }
