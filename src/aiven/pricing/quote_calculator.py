from __future__ import annotations
from aiven.utils.money import round_currency, add_margin

def calculate_supplier_total(
    unit_price: float,
    quantity: int,
    moq: int = 0,
    sample_fee: float = 0.0,
    tooling_fee: float = 0.0,
    packaging_fee: float = 0.0,
    domestic_logistics_fee: float = 0.0,
    qc_fee: float = 0.0,
) -> dict:
    warnings = []
    calc_quantity = quantity

    if moq > 0 and quantity < moq:
        warnings.append(f"Order quantity ({quantity}) is below supplier MOQ ({moq}). Minimum billable quantity is {moq}.")
        calc_quantity = moq

    unit_subtotal = float(round_currency(unit_price * calc_quantity))
    total = unit_subtotal + sample_fee + tooling_fee + packaging_fee + domestic_logistics_fee + qc_fee
    total = float(round_currency(total))

    trace = [
        f"Unit price: {unit_price} × {calc_quantity} pcs = {unit_subtotal}",
        f"Sample fee: +{sample_fee}",
        f"Tooling fee: +{tooling_fee}",
        f"Packaging: +{packaging_fee}",
        f"Domestic logistics: +{domestic_logistics_fee}",
        f"QC fee: +{qc_fee}",
        f"Supplier total: {total}",
    ]

    return {
        "quantity_billed": calc_quantity,
        "unit_subtotal": unit_subtotal,
        "supplier_total": total,
        "calculation_trace": trace,
        "warnings": warnings,
    }

def calculate_buyer_quote(
    unit_price: float,
    quantity: int,
    moq: int = 0,
    sample_fee: float = 0.0,
    tooling_fee: float = 0.0,
    packaging_fee: float = 0.0,
    domestic_logistics_fee: float = 0.0,
    international_logistics_fee: float = 0.0,
    qc_fee: float = 0.0,
    margin_rate: float = 0.15,
    fixed_margin: float = 0.0,
    currency: str = "USD",
    supplier_id: str = "",
    candidate_id: str = "",
) -> dict:
    supplier_calc = calculate_supplier_total(
        unit_price, quantity, moq, sample_fee, tooling_fee, packaging_fee, domestic_logistics_fee, qc_fee
    )
    calc_quantity = supplier_calc["quantity_billed"]
    supplier_total = supplier_calc["supplier_total"]
    warnings = list(supplier_calc["warnings"])

    total_cost = supplier_total + international_logistics_fee
    if fixed_margin > 0:
        buyer_total = float(round_currency(total_cost + fixed_margin))
        margin_amount_val = fixed_margin
        effective_margin = float(round_currency(fixed_margin / buyer_total)) if buyer_total > 0 else 0.0
    elif margin_rate > 0:
        buyer_total = float(round_currency(total_cost / (1 - margin_rate)))
        margin_amount_val = float(round_currency(buyer_total - total_cost))
        effective_margin = margin_rate
    else:
        buyer_total = total_cost
        margin_amount_val = 0.0
        effective_margin = 0.0

    buyer_unit_price = float(round_currency(buyer_total / calc_quantity)) if calc_quantity > 0 else 0.0

    trace = supplier_calc["calculation_trace"] + [
        f"International logistics: +{international_logistics_fee}",
        f"Total cost: {total_cost}",
        f"Margin: {margin_rate*100:.0f}%",
        f"Buyer total: {buyer_total}",
        f"Buyer unit price: {buyer_unit_price} {currency}",
    ]

    return {
        "supplier_id": supplier_id,
        "candidate_id": candidate_id,
        "unit_price": unit_price,
        "quantity": quantity,
        "moq": moq,
        "sample_fee": sample_fee,
        "tooling_fee": tooling_fee,
        "packaging_fee": packaging_fee,
        "domestic_logistics_fee": domestic_logistics_fee,
        "international_logistics_fee": international_logistics_fee,
        "qc_fee": qc_fee,
        "margin_rate": margin_rate,
        "fixed_margin": fixed_margin,
        "currency": currency,
        "supplier_total": supplier_total,
        "buyer_unit_price": buyer_unit_price,
        "buyer_total": buyer_total,
        "margin_amount": margin_amount_val,
        "effective_margin_rate": effective_margin,
        "calculation_trace": trace,
        "warnings": warnings,
    }
