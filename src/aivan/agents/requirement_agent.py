from __future__ import annotations
from aivan.schemas.requirement import BuyerRequirement, MissingField
from aivan.llm.gateway import llm_complete_json
from aivan.llm.prompts import REQUIREMENT_STRUCTURING_SYSTEM
from aivan.utils.language import detect_language

APPAREL_REQUIRED_FIELDS = [
    ("quantity", "Order quantity", "订购数量是多少？"),
    ("product_type", "Product type/description", "具体产品是什么？"),
    ("fabric_material", "Fabric/material", "面料/材质是什么？"),
    ("gsm", "Fabric weight (GSM)", "面料克重/GSM是多少？"),
    ("color", "Color", "颜色是什么？"),
    ("size_ratio", "Size ratio breakdown", "尺码比例是多少？"),
    ("packaging", "Packaging type", "包装方式是什么？"),
    ("destination", "Destination country/city", "目的地是哪里？"),
    ("delivery_days", "Delivery deadline (days)", "需要多少天内交货？"),
]

CNC_REQUIRED_FIELDS = [
    ("quantity", "Order quantity", "订购数量是多少？"),
    ("material_spec", "Material specification", "材料规格是什么？"),
    ("tolerance", "Tolerance requirements", "公差要求是多少？"),
    ("destination", "Destination", "目的地是哪里？"),
    ("delivery_days", "Delivery deadline", "需要多少天内交货？"),
]

def _deterministic_parse(raw_text: str) -> dict:
    """Fallback: detect basic fields from raw text without LLM."""
    import re
    result = {}
    text_lower = raw_text.lower()

    qty_match = re.search(r'(\d[\d,]*)\s*(?:件|pcs|pieces|units)', raw_text)
    if qty_match:
        result["quantity"] = int(qty_match.group(1).replace(",", ""))

    if any(w in text_lower for w in ["shirt", "衬衣", "衬衫", "t-shirt", "polo"]):
        result["category"] = "apparel"
        result["product_type"] = "shirt"
    elif any(w in text_lower for w in ["cnc", "machining", "mill", "lathe"]):
        result["category"] = "cnc"

    gsm_match = re.search(r'(\d+)\s*gsm', text_lower)
    if gsm_match:
        result["gsm"] = int(gsm_match.group(1))

    if "cotton" in text_lower or "纯棉" in text_lower:
        result["fabric_material"] = "100% cotton"
    if "white" in text_lower or "白色" in text_lower:
        result["color"] = "white"

    for city in ["Vancouver", "Los Angeles", "New York", "London", "Shanghai", "温哥华", "洛杉矶", "纽约"]:
        if city.lower() in text_lower or city in raw_text:
            result["destination"] = city
            break

    day_match = re.search(r'(\d+)\s*(?:days?|天|日)', text_lower)
    if day_match:
        result["delivery_days"] = int(day_match.group(1))

    price_match = re.search(r'(?:usd|美元|＄|\$)\s*([\d.]+)', text_lower)
    if price_match:
        result["target_unit_price"] = float(price_match.group(1))

    if "ddp" in text_lower:
        result["incoterms"] = "DDP"
    elif "fob" in text_lower:
        result["incoterms"] = "FOB"

    if "air" in text_lower or "空运" in text_lower:
        result["logistics_preference"] = "air"
    elif "sea" in text_lower or "海运" in text_lower:
        result["logistics_preference"] = "sea"

    return result

def _detect_missing_fields(req: BuyerRequirement) -> list[MissingField]:
    missing = []
    category = req.category.lower() if req.category else "apparel"

    fields = CNC_REQUIRED_FIELDS if "cnc" in category else APPAREL_REQUIRED_FIELDS

    for field_name, description, question in fields:
        val = getattr(req, field_name, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(MissingField(field_name=field_name, description=description, question=question))

    return missing

def structure_customer_requirement_with_llm(
    raw_text: str,
    attachments: list | None = None,
    existing_requirement: BuyerRequirement | None = None,
    project_id: str = "",
) -> BuyerRequirement:
    """Structure a customer requirement using LLM, with deterministic fallback."""
    language = detect_language(raw_text)

    attach_note = ""
    if attachments:
        attach_note = f"\n\nAttachments: {len(attachments)} file(s) attached."
        for a in attachments:
            if isinstance(a, dict):
                attach_note += f"\n- {a.get('filename', 'unnamed')} ({a.get('type', 'unknown')})"

    existing_note = ""
    if existing_requirement:
        existing_note = f"\n\nPrevious requirement context: category={existing_requirement.category}, product={existing_requirement.product_type}"

    user_prompt = f"Customer message:\n{raw_text}{attach_note}{existing_note}\n\nExtract and structure all requirement fields. Language: {language}"

    try:
        result = llm_complete_json("requirement_structuring", REQUIREMENT_STRUCTURING_SYSTEM, user_prompt)
    except Exception:
        result = {}

    if not result or result.get("confidence", 0) < 0.3:
        result = _deterministic_parse(raw_text)
        result["language"] = language
        result["confidence"] = 0.5

    if existing_requirement:
        for field in BuyerRequirement.model_fields:
            if field not in result and getattr(existing_requirement, field, None):
                existing_val = getattr(existing_requirement, field)
                if existing_val is not None and existing_val != "" and existing_val != []:
                    result[field] = existing_val

    missing_raw = result.pop("missing_fields", [])

    safe_data = {k: v for k, v in result.items() if k in BuyerRequirement.model_fields and k not in ("missing_fields", "project_id", "raw_text")}
    req = BuyerRequirement(project_id=project_id, raw_text=raw_text, **safe_data)

    req.missing_fields = _detect_missing_fields(req)

    if not req.category:
        text_lower = raw_text.lower()
        if any(w in text_lower for w in ["shirt", "衬衣", "衬衫", "apparel", "garment", "textile", "fabric"]):
            req.category = "apparel"
        elif any(w in text_lower for w in ["cnc", "machining", "mill", "lathe", "metal"]):
            req.category = "cnc"
        else:
            req.category = "general"

    return req
