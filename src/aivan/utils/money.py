from decimal import Decimal, ROUND_HALF_UP

def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def round_currency(value, places: int = 2) -> Decimal:
    d = to_decimal(value)
    quantize_str = "0." + "0" * places
    return d.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)

def add_margin(cost: float, margin_rate: float) -> float:
    if margin_rate <= 0:
        return cost
    return float(round_currency(to_decimal(cost) / (1 - to_decimal(margin_rate))))

def margin_amount(selling: float, cost: float) -> float:
    return float(round_currency(to_decimal(selling) - to_decimal(cost)))

def margin_rate(selling: float, cost: float) -> float:
    if selling == 0:
        return 0.0
    return float(round_currency((to_decimal(selling) - to_decimal(cost)) / to_decimal(selling)))
