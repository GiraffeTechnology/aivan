"""Canonical English customer drafts from verified requirement and quote fields.

This is presentation only. Pricing, option selection and feasibility remain
owned by their existing calculators and service results. Non-English output
continues through the shared language service after draft creation.
"""

from __future__ import annotations

import math
from decimal import Decimal

from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.schemas.quote import BuyerOption, QuoteCalculation
from aivan.schemas.requirement import BuyerRequirement


def deadline_warning(
    estimate: LeadTimeEstimate, requested_deadline: int | None, *, include_values: bool = True
) -> str | None:
    """Explain the returned feasibility without substituting P50 for P80."""
    if estimate.deadline_feasible is not False:
        return None
    deadline = (
        estimate.deadline_days
        if estimate.deadline_days is not None
        else requested_deadline
    )
    if deadline is not None and estimate.p80_days > deadline:
        if not include_values:
            # The independently labelled P80 and assessed-deadline lines retain
            # their exact values. Keep this explanation to a single proposition
            # so outbound translation cannot swap two quantities in one clause.
            return "The P80 lead-time estimate exceeds the assessed deadline."
        return (
            f"The P80 lead-time estimate ({estimate.p80_days} days) "
            f"exceeds the {deadline}-day deadline."
        )
    # GLTG may report infeasibility for reasons other than this comparison.
    # Preserve that result without inventing a numerical explanation.
    return "GLTG reports that the deadline is not feasible. Human review is required."


def _known_amount(quote: QuoteCalculation, field: str) -> bool:
    value = getattr(quote, field)
    return field in quote.model_fields_set and math.isfinite(value) and value >= 0


def _display_amount(value: float) -> str:
    """Group the exact stored decimal representation without rounding it."""
    return format(Decimal(str(value)), ",f")


def _option_summary(option: BuyerOption, requirement: BuyerRequirement | None) -> str:
    lines = [option.option_label]
    quantity = requirement.quantity if requirement else None
    quantity_unit = (requirement.quantity_unit or "").strip() if requirement else ""
    if quantity is not None and quantity > 0:
        suffix = f" {quantity_unit}" if quantity_unit else ""
        lines.append(f"Requested quantity: {quantity}{suffix}.")
    else:
        lines.append("Requested quantity: Not confirmed.")

    quote = option.quote
    # Older generation paths use a fallback calculation quantity. It must not
    # become a commercial offer when the buyer's actual quantity is unknown or
    # differs from the quotation. Do not recompute or round stored amounts here.
    quote_basis_known = (
        quote is not None
        and quantity is not None
        and quantity > 0
        and quote.quantity == quantity
        and "currency" in quote.model_fields_set
        and bool(quote.currency.strip())
    )
    if quote_basis_known and quote is not None and quantity is not None:
        if quote.moq > quantity:
            suffix = f" {quantity_unit}" if quantity_unit else ""
            lines.append(f"Minimum billable quantity: {quote.moq}{suffix}.")
        currency = quote.currency.strip()
        lines.append(
            f"Buyer unit price: {currency} {_display_amount(quote.buyer_unit_price)}."
            if _known_amount(quote, "buyer_unit_price")
            else "Buyer unit price: Not confirmed."
        )
        lines.append(
            f"Total amount: {currency} {_display_amount(quote.buyer_total)}."
            if _known_amount(quote, "buyer_total")
            else "Total amount: Not confirmed."
        )
    else:
        lines.extend(("Buyer unit price: Not confirmed.", "Total amount: Not confirmed."))
        if quantity is None or quantity <= 0:
            lines.append("Please confirm the order quantity before finalizing this quotation.")
        elif quote is not None and quote.quantity != quantity:
            lines.append(
                "The quotation quantity differs from the requested quantity. "
                "Please confirm the quantity and request an updated quotation."
            )
        else:
            lines.append("Please confirm the price and currency before finalizing this quotation.")

    estimate = option.lead_time_estimate
    if estimate is not None:
        lines.extend(
            (
                f"Estimated lead time at P50: {estimate.p50_days} days.",
                f"Estimated lead time at P80: {estimate.p80_days} days.",
                f"Estimated lead time at P90: {estimate.p90_days} days.",
            )
        )
        requested_deadline = requirement.delivery_days if requirement else None
        if estimate.deadline_days is not None and estimate.deadline_days != requested_deadline:
            lines.append(f"Deadline assessed by GLTG: {estimate.deadline_days} days.")
        warning = deadline_warning(estimate, requested_deadline, include_values=False)
        if warning:
            lines.append(f"Deadline warning: {warning}")
        elif estimate.deadline_feasible is None:
            lines.append("Deadline feasibility: Not confirmed.")
        else:
            lines.append("GLTG assesses the deadline as feasible. This is an estimate.")
        risk_labels = {
            "low": "low",
            "medium": "medium",
            "medium_high": "medium to high",
            "high": "high",
            "critical": "critical",
        }
        risk_label = risk_labels.get(estimate.deadline_risk_level, "not confirmed")
        lines.append(f"Deadline risk level: {risk_label}.")
        lines.append("Lead-time estimates are not a delivery guarantee.")
    else:
        lines.append("Lead-time estimate and deadline feasibility: Not confirmed.")

    # Do not echo internal ranking reasoning or calculation traces: they may
    # contain supplier cost/identity even when those fields are confidential.
    for warning in option.warnings:
        if estimate is not None and warning == deadline_warning(
            estimate, requirement.delivery_days if requirement else None
        ):
            continue
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def format_customer_quote_draft(
    options: list[BuyerOption],
    requirement: BuyerRequirement | None,
    *,
    gpm_guidance: dict | None = None,
) -> str:
    """Render known customer-facing facts without inventing missing terms."""
    paragraphs = ["We have received supplier quotes. Here are the current options:"]
    product = (requirement.product_type or "").strip() if requirement else ""
    details = [f"Product: {product}." if product else "Product: Not confirmed."]
    if requirement is not None and requirement.delivery_days is not None:
        details.append(f"Requested deadline: {requirement.delivery_days} days.")
    paragraphs.append("\n".join(details))
    paragraphs.extend(_option_summary(option, requirement) for option in options)
    if gpm_guidance:
        recommendations = {
            "human_review_required": "Human review is required.",
            "accept": "Acceptance is recommended for human review.",
            "negotiate": "Negotiation is recommended.",
            "reject": "Rejection is recommended for human review.",
            "request_more_info": "More information is needed.",
        }
        recommendation = recommendations.get(
            gpm_guidance.get("recommendation"), "Review the pricing guidance before deciding."
        )
        confidence = gpm_guidance.get("confidence")
        confidence_text = confidence if confidence in {"low", "medium", "high"} else "not confirmed"
        paragraphs.append(f"Pricing guidance: {recommendation}\nConfidence: {confidence_text}.")
    paragraphs.append("Human approval is still required.")
    paragraphs.append("Please let us know which option you prefer.")
    return "\n\n".join(paragraphs)
