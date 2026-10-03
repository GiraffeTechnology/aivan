from __future__ import annotations
import os
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.schemas.quote import BuyerOption, QuoteCalculation
from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.llm.gateway import llm_complete_json
from aivan.llm.prompts import BUYER_OPTION_SYSTEM
from aivan.pricing.quote_calculator import calculate_buyer_quote
from aivan.pricing.margin import should_hide_supplier_identity, should_hide_supplier_price, get_default_margin_rate
from aivan.utils.ids import new_id
from aivan.execution.source_quote import source_quote_reference

def generate_buyer_options(
    requirement: BuyerRequirement,
    supplier_replies: list[SupplierReply],
    lead_time_estimates: list[LeadTimeEstimate],
    project_id: str,
) -> list[BuyerOption]:
    """Generate Top-3 buyer-facing options from supplier replies."""
    if not supplier_replies:
        return []

    current_by_supplier: dict[str, SupplierReply] = {}
    anonymous_replies: list[SupplierReply] = []
    for reply in supplier_replies:
        if reply.unit_price is None:
            continue
        business_identity = (reply.supplier_id or reply.candidate_id).strip()
        if business_identity:
            # Input order is revision order in the persisted project payload;
            # the latest valid revision replaces the older active one.
            current_by_supplier[business_identity] = reply
        else:
            anonymous_replies.append(reply)
    valid_replies = [*current_by_supplier.values(), *anonymous_replies]
    if not valid_replies:
        return []

    normalized_currencies = [
        (reply.currency or "").strip().upper() for reply in valid_replies
    ]
    currencies = {currency for currency in normalized_currencies if currency}
    supported_quantity_units = {"pc", "pcs", "piece", "pieces"}
    price_basis_comparable = (
        all(normalized_currencies)
        and len(currencies) == 1
        and (requirement.quantity_unit or "").strip().lower()
        in supported_quantity_units
    )

    lt_by_id: dict[str, LeadTimeEstimate] = {}
    for lt in lead_time_estimates:
        if lt.supplier_id:
            lt_by_id[lt.supplier_id] = lt
        if lt.candidate_id:
            lt_by_id[lt.candidate_id] = lt

    scored = []
    for reply in valid_replies:
        lt = lt_by_id.get(reply.supplier_id) or lt_by_id.get(reply.candidate_id)
        deadline_days = requirement.delivery_days

        target_currency_matches = (
            not requirement.target_currency
            or requirement.target_currency.strip().upper()
            == (reply.currency or "").strip().upper()
        )
        if not price_basis_comparable or not target_currency_matches:
            price_score = 0.5
        else:
            price_score = 1.0 - min(
                1.0,
                max(
                    0.0,
                    (
                        reply.unit_price
                        - (requirement.target_unit_price or reply.unit_price)
                    )
                    / max(requirement.target_unit_price or 1, 0.01),
                ),
            )
        lt_score = 1.0
        if lt and deadline_days:
            if lt.deadline_feasible is False:
                lt_score = 0.1
            elif lt.deadline_risk_level == "critical":
                lt_score = 0.2
            elif lt.deadline_risk_level == "high":
                lt_score = 0.5
            elif lt.deadline_risk_level == "medium":
                lt_score = 0.7
            else:
                lt_score = 1.0

        overall = lt_score * 0.40 + price_score * 0.35 + 0.25
        scored.append((reply, lt, overall, lt_score, price_score))

    scored.sort(key=lambda x: x[2], reverse=True)

    options = []
    hide_identity = should_hide_supplier_identity()
    hide_price = should_hide_supplier_price()
    margin_rate = get_default_margin_rate()

    def make_option(reply: SupplierReply, lt: LeadTimeEstimate | None, option_type: str, option_label: str, reasoning: str) -> BuyerOption:
        sup_display = "Supplier (confidential)" if hide_identity else (reply.supplier_id or reply.candidate_id or "Unknown")

        quote_data = calculate_buyer_quote(
            unit_price=reply.unit_price,
            quantity=requirement.quantity or 1000,
            moq=reply.moq or 0,
            margin_rate=margin_rate,
        )
        quote = QuoteCalculation(
            supplier_id=reply.supplier_id,
            candidate_id=reply.candidate_id,
            unit_price=quote_data["unit_price"] if not hide_price else 0.0,
            quantity=requirement.quantity or 1000,
            moq=reply.moq or 0,
            margin_rate=margin_rate,
            currency=reply.currency,
            supplier_total=quote_data["supplier_total"] if not hide_price else 0.0,
            buyer_unit_price=quote_data["buyer_unit_price"],
            buyer_total=quote_data["buyer_total"],
            margin_amount=quote_data["margin_amount"],
            effective_margin_rate=quote_data["effective_margin_rate"],
            calculation_trace=quote_data["calculation_trace"] if not hide_price else ["Supplier cost confidential"],
            warnings=quote_data["warnings"],
        )

        warnings = []
        if not price_basis_comparable:
            warnings.append(
                "Quote currencies or unit bases are not directly comparable; "
                "no lowest-cost ranking was applied."
            )
        if lt and lt.deadline_feasible is False:
            warnings.append(f"Lead time ({lt.expected_days} days) exceeds your deadline ({requirement.delivery_days} days).")
        if reply.moq and requirement.quantity and requirement.quantity < reply.moq:
            warnings.append(f"Your order quantity ({requirement.quantity}) is below supplier MOQ ({reply.moq}).")
        if lt and "lead_time_too_aggressive" in (getattr(reply, "risks", []) or []):
            warnings.append("Supplier's stated lead time appears aggressive vs calculated estimate.")

        return BuyerOption(
            option_id=f"opt_{new_id()}",
            project_id=project_id,
            option_label=option_label,
            option_type=option_type,
            supplier_id=reply.supplier_id,
            candidate_id=reply.candidate_id,
            supplier_display_name=sup_display,
            source_quote_reference=source_quote_reference(reply),
            lead_time_estimate=lt,
            quote=quote,
            risk_level="low" if not reply.risks else "medium",
            deadline_feasible=lt.deadline_feasible if lt else None,
            deadline_risk_level=lt.deadline_risk_level if lt else "unknown",
            reasoning=reasoning,
            warnings=warnings,
            status="draft",
        )

    by_lt = sorted(
        (item for item in scored if item[1] is not None),
        key=lambda x: (x[1].expected_days, x[0].supplier_id or x[0].candidate_id),
    )
    by_price = (
        sorted(scored, key=lambda x: (x[0].unit_price or 999, -x[3]))
        if price_basis_comparable
        else []
    )
    added: set[str] = set()
    result_options = []

    def reply_key(reply: SupplierReply) -> str:
        return reply.supplier_id or reply.candidate_id or reply.raw_text

    if by_lt:
        r, lt, _, lt_s, p_s = by_lt[0]
        reason = f"Fastest option: {'estimated ' + str(lt.expected_days) + ' days delivery' if lt else 'shortest stated lead time'}"
        if lt and lt.deadline_feasible is False:
            reason += f" (WARNING: may not meet {requirement.delivery_days}-day deadline)"
        opt = make_option(r, lt, "fastest", "Option A — Fastest", reason)
        result_options.append(opt)
        added.add(reply_key(r))

    if by_price:
        r, lt, _, _, _ = by_price[0]
        if reply_key(r) not in added:
            reason = f"Lowest cost: {r.currency} {r.unit_price:.2f}/pc"
            opt = make_option(r, lt, "lowest_cost", "Option B — Lowest Cost", reason)
            result_options.append(opt)
            added.add(reply_key(r))
        elif len(by_price) > 1:
            r, lt, _, _, _ = by_price[1]
            reason = f"Next comparable quote: {r.currency} {r.unit_price:.2f}/pc"
            opt = make_option(r, lt, "lowest_cost", "Option B — Best Value", reason)
            result_options.append(opt)
            added.add(reply_key(r))

    if len(result_options) < 2 and scored:
        for r, lt, score, _, _ in scored:
            if reply_key(r) not in added:
                label = f"Option {chr(65+len(result_options))} — Alternative"
                opt = make_option(r, lt, "alternative", label, "Additional option for consideration")
                result_options.append(opt)
                added.add(reply_key(r))
                if len(result_options) >= 3:
                    break

    return result_options
