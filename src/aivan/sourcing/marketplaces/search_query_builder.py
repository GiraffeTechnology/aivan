from __future__ import annotations

def build_marketplace_queries(requirement) -> list[str]:
    """Generate marketplace search queries from a BuyerRequirement."""
    from aivan.llm.gateway import llm_complete_json
    from aivan.llm.prompts import MARKETPLACE_QUERY_SYSTEM

    parts = []
    if hasattr(requirement, "product_type") and requirement.product_type:
        parts.append(requirement.product_type)
    if hasattr(requirement, "fabric_material") and requirement.fabric_material:
        parts.append(requirement.fabric_material)
    if hasattr(requirement, "gsm") and requirement.gsm:
        parts.append(f"{requirement.gsm}gsm")
    if hasattr(requirement, "color") and requirement.color:
        parts.append(requirement.color)

    base_query = " ".join(parts)

    user_prompt = f"""Customer requirement:
Product: {getattr(requirement, 'product_type', '')}
Material: {getattr(requirement, 'fabric_material', '')}
GSM: {getattr(requirement, 'gsm', '')}
Color: {getattr(requirement, 'color', '')}
Quantity: {getattr(requirement, 'quantity', '')}
Destination: {getattr(requirement, 'destination', '')}

Generate 4-6 marketplace search queries (mix of English and Chinese)."""

    try:
        result = llm_complete_json("marketplace_search_query_generation", MARKETPLACE_QUERY_SYSTEM, user_prompt)
        queries = result.get("queries", [])
        if queries and isinstance(queries, list):
            return queries
    except Exception:
        pass

    qty = getattr(requirement, "quantity", None)
    qty_str = f"MOQ {qty}" if qty else ""
    return [
        f"{base_query} manufacturer {qty_str}".strip(),
        f"{base_query} factory wholesale".strip(),
        f"{getattr(requirement, 'product_type', '')} {getattr(requirement, 'fabric_material', '')} 工厂".strip(),
    ]
