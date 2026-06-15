from __future__ import annotations
import os
from aivan.risk.models import SupplierRiskSearchPlan, SupplierRiskReport
from aivan.risk.web_search import get_web_search_provider
from aivan.risk.search_providers import get_search_provider_for_risk
from aivan.risk.evidence_extractor import extract_evidence_from_search_results
from aivan.risk.risk_scorer import score_supplier_risk
from aivan.utils.ids import new_risk_report_id
from aivan.utils.time_utils import utcnow_iso

def generate_risk_search_plan(supplier_name: str, category: str = "") -> SupplierRiskSearchPlan:
    from aivan.llm.gateway import llm_complete_json
    from aivan.llm.prompts import RISK_SEARCH_PLAN_SYSTEM

    user_prompt = f"Supplier name: {supplier_name}\nProduct category: {category}\n\nGenerate a comprehensive web search plan to verify this supplier."
    try:
        result = llm_complete_json("supplier_risk_search_planning", RISK_SEARCH_PLAN_SYSTEM, user_prompt)
        return SupplierRiskSearchPlan(**{k: v for k, v in result.items() if k in SupplierRiskSearchPlan.model_fields})
    except Exception:
        return SupplierRiskSearchPlan(
            supplier_name_queries=[f"{supplier_name} company profile"],
            complaint_queries=[f"{supplier_name} complaints scam reviews"],
            sanctions_or_restriction_queries=[f"{supplier_name} sanctions blacklist"],
            reason=f"Automated search plan for unknown supplier: {supplier_name}",
        )

def run_risk_screening(
    supplier_name: str,
    supplier_id: str | None = None,
    candidate_id: str | None = None,
    category: str = "",
    existing_flags: list[str] = None,
    risk_profile: str = "medium",
) -> SupplierRiskReport:
    """Run a full risk screening for an unknown supplier."""
    if not os.environ.get("AIVAN_ENABLE_UNKNOWN_SUPPLIER_RISK_SEARCH", "true").lower() == "true":
        from aivan.risk.models import SupplierRiskScore
        return SupplierRiskReport(
            report_id=new_risk_report_id(),
            supplier_id=supplier_id,
            candidate_id=candidate_id,
            supplier_name=supplier_name,
            risk_score=SupplierRiskScore(
                supplier_id=supplier_id,
                candidate_id=candidate_id,
                risk_level="unknown",
                recommended_action="manual_review_required",
            ),
            notes="Risk screening disabled.",
            created_at=utcnow_iso(),
        )

    plan = generate_risk_search_plan(supplier_name, category)
    all_queries = (
        plan.supplier_name_queries
        + plan.platform_store_queries
        + plan.complaint_queries
        + plan.sanctions_or_restriction_queries
    )[:8]

    provider = get_search_provider_for_risk(supplier_name)
    all_results = []
    for query in all_queries:
        try:
            results = provider.search(query, limit=3)
            all_results.extend(results)
        except Exception:
            pass

    evidence = extract_evidence_from_search_results(all_results, supplier_name)
    flags = list(existing_flags or [])
    if not flags:
        flags.append("identity_unverified")

    risk_score = score_supplier_risk(evidence, supplier_id, candidate_id, flags)

    return SupplierRiskReport(
        report_id=new_risk_report_id(),
        supplier_id=supplier_id,
        candidate_id=candidate_id,
        supplier_name=supplier_name,
        risk_score=risk_score,
        evidence=evidence,
        search_plan_summary=f"Searched {len(all_queries)} queries, found {len(evidence)} evidence items.",
        created_at=utcnow_iso(),
        notes=f"Risk level: {risk_score.risk_level}. Recommended: {risk_score.recommended_action}",
    )
