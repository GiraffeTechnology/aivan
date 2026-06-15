import os
from aiven.utils.money import round_currency

def get_default_margin_rate() -> float:
    return float(os.environ.get("AIVAN_DEFAULT_MARGIN_RATE", "0.15"))

def should_hide_supplier_identity() -> bool:
    return os.environ.get("AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER", "true").lower() == "true"

def should_hide_supplier_price() -> bool:
    return os.environ.get("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "true").lower() == "true"

def apply_margin(cost: float, margin_rate: float | None = None) -> float:
    rate = margin_rate if margin_rate is not None else get_default_margin_rate()
    if rate <= 0:
        return cost
    return float(round_currency(cost / (1 - rate)))

def calculate_margin_breakdown(cost: float, selling: float) -> dict:
    margin_amt = float(round_currency(selling - cost))
    margin_rate = float(round_currency(margin_amt / selling)) if selling > 0 else 0.0
    return {
        "cost": cost,
        "selling": selling,
        "margin_amount": margin_amt,
        "margin_rate": margin_rate,
        "margin_pct": f"{margin_rate*100:.1f}%",
    }
