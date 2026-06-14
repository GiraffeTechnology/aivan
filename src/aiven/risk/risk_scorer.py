from __future__ import annotations
from aiven.risk.models import SupplierRiskEvidence, SupplierRiskScore

CRITICAL_RISK_SIGNALS = {"sanction", "blacklist", "fraud", "court", "violation", "lawsuit"}
HIGH_RISK_SIGNALS = {"scam", "fake", "complaint", "non-delivery"}
MEDIUM_RISK_FLAGS = {"storefront_new_or_low_history", "capacity_claim_unverified", "certificate_unverified"}

def score_supplier_risk(
    evidence: list[SupplierRiskEvidence],
    supplier_id: str | None = None,
    candidate_id: str | None = None,
    existing_flags: list[str] = None,
) -> SupplierRiskScore:
    if existing_flags is None:
        existing_flags = []

    negative_signals = []
    positive_signals = []
    risk_flags = list(existing_flags)

    for ev in evidence:
        if ev.risk_signal:
            signal_lower = ev.risk_signal.lower()
            if any(c in signal_lower for c in CRITICAL_RISK_SIGNALS):
                negative_signals.append(("critical", ev.risk_signal, ev.reliability_score))
            elif any(h in signal_lower for h in HIGH_RISK_SIGNALS):
                negative_signals.append(("high", ev.risk_signal, ev.reliability_score))
            else:
                negative_signals.append(("medium", ev.risk_signal, ev.reliability_score))
        for s in ev.supports_claims:
            if "positive_signal" in s:
                positive_signals.append(s.replace("positive_signal:", ""))

    risk_score = 0.0
    for level, signal, reliability in negative_signals:
        if level == "critical":
            risk_score += 0.6 * reliability
        elif level == "high":
            risk_score += 0.3 * reliability
        else:
            risk_score += 0.15 * reliability

    risk_score -= len(positive_signals) * 0.05
    risk_score = max(0.0, min(1.0, risk_score))

    if risk_score >= 0.7 or any("sanction" in s or "fraud" in s or "court" in s for _, s, _ in negative_signals):
        risk_level = "critical"
        recommended_action = "do_not_contact"
        if "sanctions_or_restriction_signal" not in risk_flags:
            risk_flags.append("sanctions_or_restriction_signal")
    elif risk_score >= 0.45 or any(level == "high" for level, _, _ in negative_signals):
        risk_level = "high"
        recommended_action = "avoid_until_verified"
        if "negative_public_complaints" not in risk_flags:
            risk_flags.append("negative_public_complaints")
    elif risk_score >= 0.25 or len(negative_signals) > 0:
        risk_level = "medium"
        recommended_action = "contact_but_verify"
    elif len(evidence) == 0:
        risk_level = "unknown"
        recommended_action = "manual_review_required"
        if "insufficient_public_presence" not in risk_flags:
            risk_flags.append("insufficient_public_presence")
    else:
        risk_level = "low"
        recommended_action = "safe_to_contact"

    confidence = min(0.9, 0.3 + len(evidence) * 0.08)

    missing = []
    has_platform = any(ev.source_type == "platform" for ev in evidence)
    has_legal = any(ev.source_type in ("government", "legal") for ev in evidence)
    if not has_platform:
        missing.append("platform storefront verification")
    if not has_legal:
        missing.append("sanctions/legal database check")
    if len(positive_signals) == 0:
        missing.append("factory verification")

    return SupplierRiskScore(
        supplier_id=supplier_id,
        candidate_id=candidate_id,
        risk_level=risk_level,
        risk_score=risk_score,
        confidence_score=confidence,
        positive_signals=positive_signals,
        risk_flags=risk_flags,
        evidence_count=len(evidence),
        missing_evidence=missing,
        recommended_action=recommended_action,
    )
