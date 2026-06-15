from __future__ import annotations
from aivan.risk.models import SupplierRiskEvidence, SearchResult
from aivan.utils.ids import new_evidence_id
from aivan.utils.time_utils import utcnow_iso

NEGATIVE_KEYWORDS = ["scam", "fraud", "fake", "complaint", "non-delivery", "sanction", "blacklist", "lawsuit", "court", "violation"]
POSITIVE_KEYWORDS = ["verified", "certified", "gold supplier", "trade assurance", "iso", "established", "award"]

def extract_evidence_from_search_results(
    results: list[SearchResult],
    supplier_name: str,
) -> list[SupplierRiskEvidence]:
    evidence_list = []
    for r in results:
        text_lower = (r.title + " " + r.snippet).lower()
        risk_signal = None
        reliability = 0.5

        neg_hits = [k for k in NEGATIVE_KEYWORDS if k in text_lower]
        pos_hits = [k for k in POSITIVE_KEYWORDS if k in text_lower]

        if neg_hits:
            risk_signal = neg_hits[0]
            reliability = 0.7 if r.source_type in ("government", "legal") else 0.5
        elif pos_hits:
            risk_signal = None
            reliability = 0.6

        relevance = "high" if supplier_name.lower().split()[0] in text_lower else "medium"
        if r.source_type in ("government", "legal"):
            reliability = max(reliability, 0.8)
        elif r.source_type == "platform":
            reliability = max(reliability, 0.6)

        supports = []
        contradicts = []
        if pos_hits:
            supports = [f"positive_signal:{h}" for h in pos_hits]
        if neg_hits:
            contradicts = [f"risk_signal:{h}" for h in neg_hits]

        ev = SupplierRiskEvidence(
            evidence_id=new_evidence_id(),
            source_type=r.source_type,
            title=r.title,
            url=r.url or None,
            publisher=r.publisher or None,
            published_date=r.published_date or None,
            fetched_at=utcnow_iso(),
            snippet=r.snippet,
            relevance=relevance,
            reliability_score=reliability,
            risk_signal=risk_signal,
            supports_claims=supports,
            contradicts_claims=contradicts,
        )
        evidence_list.append(ev)
    return evidence_list
