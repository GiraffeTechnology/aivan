from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from aivan.db.models.intake import InquirySheet
from aivan.intake.rfq_structuring import normalized_product


@dataclass(frozen=True)
class MatchDecision:
    decision: str
    confidence: float
    reason: str
    sheet: InquirySheet | None = None


def match_inquiry_sheet(structured: dict, context: dict, db: Session) -> MatchDecision:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    candidates = (
        db.query(InquirySheet)
        .filter(InquirySheet.status == "active")
        .filter(InquirySheet.created_at >= cutoff)
        .order_by(InquirySheet.updated_at.desc())
        .limit(50)
        .all()
    )

    best: tuple[float, str, InquirySheet] | None = None
    for sheet in candidates:
        score, reason = _score_sheet(sheet, structured, context)
        if best is None or score > best[0]:
            best = (score, reason, sheet)

    if best and best[0] >= 0.85:
        return MatchDecision("same_existing", round(best[0], 2), best[1], best[2])

    if not _has_enough_identity(structured):
        reason = "insufficient product/quantity/destination signals; conservative uncertain handling"
        if best:
            reason = f"{reason}; best existing score={best[0]:.2f} ({best[1]})"
        return MatchDecision("uncertain_new", 0.7 if best and best[0] >= 0.6 else 0.55, reason)

    if best and best[0] >= 0.6:
        return MatchDecision(
            "uncertain_new",
            round(best[0], 2),
            f"partial match only; not merging because false merge risk is higher ({best[1]})",
        )

    reason = "no active sheet passed conservative same-inquiry threshold"
    if best:
        reason = f"{reason}; best existing score={best[0]:.2f} ({best[1]})"
    return MatchDecision("new_temporary", round(best[0], 2) if best else 0.4, reason)


def build_match_fingerprint(structured: dict, context: dict) -> str:
    parts = [
        context.get("conversation_id") or "",
        context.get("sender_id") or "",
        normalized_product(structured),
        str(structured.get("product_category") or ""),
        str(structured.get("quantity") or ""),
        str(structured.get("destination") or ""),
        str(structured.get("lead_time_days") or structured.get("delivery_deadline") or ""),
    ]
    return "|".join(part.strip().lower() for part in parts if part is not None)


def _score_sheet(sheet: InquirySheet, structured: dict, context: dict) -> tuple[float, str]:
    score = 0.0
    reasons: list[str] = []

    if _same(context.get("conversation_id"), sheet.conversation_id):
        score += 0.25
        reasons.append("same conversation")
    elif _same(context.get("sender_id"), sheet.sender_id):
        score += 0.15
        reasons.append("same sender")
    elif context.get("conversation_id") or context.get("sender_id"):
        score -= 0.1
        reasons.append("conversation/sender differs or missing")

    incoming_product = normalized_product(structured)
    sheet_product = (sheet.normalized_product or "").strip().lower()
    incoming_category = str(structured.get("product_category") or "").strip().lower()
    sheet_category = (sheet.product_category or "").strip().lower()
    if incoming_product and sheet_product and incoming_product == sheet_product:
        score += 0.3
        reasons.append("same product")
    elif incoming_category and sheet_category and incoming_category == sheet_category:
        score += 0.22
        reasons.append("same product category")
    elif incoming_product or incoming_category:
        score -= 0.35
        reasons.append("product differs")

    score += _same_or_compatible_number(
        structured.get("quantity"),
        sheet.quantity,
        same_points=0.15,
        different_penalty=0.3,
        reasons=reasons,
        label="quantity",
    )

    incoming_destination = str(structured.get("destination") or "").strip().lower()
    sheet_destination = (sheet.destination or "").strip().lower()
    if incoming_destination and sheet_destination and incoming_destination == sheet_destination:
        score += 0.15
        reasons.append("same destination")
    elif incoming_destination or sheet_destination:
        score -= 0.25
        reasons.append("destination differs or missing")

    score += _same_or_compatible_number(
        structured.get("lead_time_days"),
        sheet.lead_time_days,
        same_points=0.1,
        different_penalty=0.2,
        reasons=reasons,
        label="lead time",
    )

    if _same(structured.get("delivery_deadline"), sheet.delivery_deadline):
        score += 0.1
        reasons.append("same delivery deadline")

    if _same(structured.get("quality_level"), sheet.quality_level):
        score += 0.05
        reasons.append("same quality")

    return max(0.0, min(1.0, score)), "; ".join(reasons) or "no matching signals"


def _same(left: object, right: object) -> bool:
    return bool(str(left or "").strip()) and str(left or "").strip().lower() == str(right or "").strip().lower()


def _same_or_compatible_number(
    incoming: object,
    existing: object,
    *,
    same_points: float,
    different_penalty: float,
    reasons: list[str],
    label: str,
) -> float:
    if incoming is None or existing is None:
        return 0.0
    try:
        incoming_value = float(incoming)
        existing_value = float(existing)
    except (TypeError, ValueError):
        return 0.0
    if incoming_value == existing_value:
        reasons.append(f"same {label}")
        return same_points
    larger = max(abs(incoming_value), abs(existing_value), 1.0)
    if abs(incoming_value - existing_value) / larger <= 0.1:
        reasons.append(f"compatible {label}")
        return same_points * 0.8
    reasons.append(f"{label} differs")
    return -different_penalty


def _has_enough_identity(structured: dict) -> bool:
    has_product = bool(normalized_product(structured) or structured.get("product_category"))
    has_quantity = structured.get("quantity") is not None
    has_destination = bool(structured.get("destination"))
    has_timing = bool(structured.get("lead_time_days") or structured.get("delivery_deadline"))
    return has_product and (has_quantity or has_destination or has_timing)
