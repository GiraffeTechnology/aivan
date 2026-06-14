from __future__ import annotations
from aiven.schemas.requirement import BuyerRequirement
from aiven.sourcing.supplier_models import SupplierProfile
from aiven.sourcing.marketplaces.marketplace_models import MarketplaceSupplierCandidate
from aiven.llm.gateway import llm_complete_json
from aiven.llm.prompts import SUPPLIER_INQUIRY_SYSTEM

def draft_supplier_inquiry(
    requirement: BuyerRequirement,
    supplier: SupplierProfile | None = None,
    candidate: MarketplaceSupplierCandidate | None = None,
) -> str:
    """Draft an inquiry message to a supplier."""
    sup_name = ""
    if supplier:
        sup_name = supplier.name
    elif candidate:
        sup_name = candidate.supplier_name

    user_prompt = f"""Requirement summary:
Product: {requirement.product_type}
Quantity: {requirement.quantity} {requirement.quantity_unit}
Material: {requirement.fabric_material}
GSM: {requirement.gsm}
Color: {requirement.color}
Size ratio: {requirement.size_ratio}
Packaging: {requirement.packaging}
Destination: {requirement.destination}
Delivery: {requirement.delivery_days} days
Target price: {requirement.target_unit_price} {requirement.target_currency}
Incoterms: {requirement.incoterms}
Logistics: {requirement.logistics_preference}

Supplier: {sup_name or 'Unknown'}

Draft a professional supplier inquiry message."""

    try:
        result = llm_complete_json("supplier_inquiry_drafting", SUPPLIER_INQUIRY_SYSTEM, user_prompt)
        message_text = result.get("message_text", "")
        if message_text:
            return message_text
    except Exception:
        pass

    return f"""Dear {sup_name or 'Supplier'},

We are looking to source the following:

Product: {requirement.product_type}
Quantity: {requirement.quantity} {requirement.quantity_unit}
Material: {requirement.fabric_material} {f'({requirement.gsm}gsm)' if requirement.gsm else ''}
Color: {requirement.color}
Size ratio: {requirement.size_ratio}
Packaging: {requirement.packaging}
Destination: {requirement.destination}
Delivery required: {requirement.delivery_days} days
Target price: {f'USD {requirement.target_unit_price}/pc or below' if requirement.target_unit_price else 'TBD'}
Incoterms: {requirement.incoterms}
Logistics: {requirement.logistics_preference}

Please confirm:
1. Unit price and MOQ
2. Daily/monthly production capacity
3. Lead time
4. Fabric/material availability
5. Sample availability and fee

Thank you for your attention. We look forward to your quote.

Best regards,
AIVEN Trade Salesperson"""
