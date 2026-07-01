from __future__ import annotations
import json

from pydantic import BaseModel
from aivan.schemas.requirement import BuyerRequirement, MissingField
from aivan.llm.gateway import llm_complete_json
from aivan.llm.prompts import REQUIREMENT_STRUCTURING_SYSTEM, REQUIREMENT_TRANSLATION_SYSTEM
from aivan.utils.language import detect_language


def _has_meaningful_value(value) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _coerce_nulls(data: dict, model: type[BaseModel]) -> dict:
    """Replace LLM-emitted ``null`` values with each field's declared default.

    Real LLM providers (Qwen, OpenAI, ...) frequently emit ``null`` for optional
    fields instead of omitting them. For a field whose type does not accept
    ``None`` (e.g. ``str``/``bool`` with a non-None default), that null would
    raise a ValidationError. We replace such nulls with the field's default (or
    default_factory result) while leaving genuinely optional fields — those whose
    default is ``None`` — untouched. Fields not declared on the model are ignored.
    """
    result = dict(data)
    for field_name, field_info in model.model_fields.items():
        if field_name not in result or result[field_name] is not None:
            continue
        if field_info.is_required():
            continue
        default = field_info.get_default(call_default_factory=True)
        if default is not None:
            result[field_name] = default
    return result


def _coerce_field_shapes(data: dict, model: type[BaseModel]) -> dict:
    result = dict(data)
    for field_name, field_info in model.model_fields.items():
        if field_name not in result:
            continue
        value = result[field_name]
        if value is None:
            continue
        if field_info.annotation is str and not isinstance(value, str):
            if isinstance(value, list):
                result[field_name] = "; ".join(str(item) for item in value if item is not None)
            elif isinstance(value, dict):
                result[field_name] = json.dumps(value, ensure_ascii=False)
            else:
                result[field_name] = str(value)
    return result


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

CITY_ALIASES = [
    ("Vancouver", "Vancouver"),
    ("温哥华", "Vancouver"),
    ("Los Angeles", "Los Angeles"),
    ("洛杉矶", "Los Angeles"),
    ("New York", "New York"),
    ("纽约", "New York"),
    ("London", "London"),
    ("伦敦", "London"),
    ("Shanghai", "Shanghai"),
    ("上海", "Shanghai"),
    ("Tokyo", "Tokyo"),
    ("东京", "Tokyo"),
    ("Osaka", "Osaka"),
    ("大阪", "Osaka"),
]

AUTHORITATIVE_DETERMINISTIC_FIELDS = {
    "quantity",
    "product_type",
    "category",
    "destination",
    "delivery_days",
    "target_unit_price",
    "incoterms",
    "logistics_preference",
}


def _merge_fill_missing(base: dict, fallback: dict) -> dict:
    result = dict(base)
    for field, value in fallback.items():
        if not _has_meaningful_value(result.get(field)):
            result[field] = value
    return result


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
    if "plaid" in text_lower or "checkered" in text_lower or "格子" in raw_text:
        result["notes"] = "plaid/checkered pattern"

    for alias, destination in CITY_ALIASES:
        if alias.lower() in text_lower or alias in raw_text:
            result["destination"] = destination
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


def _translate_requirement_to_english(raw_text: str, language: str) -> str:
    if language == "en":
        return raw_text
    prompt = (
        "Translate this customer trade inquiry into clear English for downstream RFQ extraction. "
        "Preserve quantities, units, deadlines, destinations, product descriptions, and quality requirements. "
        "Do not add, remove, or change facts.\n\n"
        f"Customer message ({language}):\n{raw_text}"
    )
    schema_hint = {"translated_text": "English translation", "confidence": "0-1"}
    try:
        result = llm_complete_json("requirement_translation", REQUIREMENT_TRANSLATION_SYSTEM, prompt, schema_hint)
    except Exception:
        return raw_text
    translated = result.get("translated_text") or result.get("translation") or result.get("text")
    if isinstance(translated, str) and translated.strip() and translated.strip().lower() != raw_text.lower():
        return translated.strip()
    return raw_text

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
    raw_deterministic = _deterministic_parse(raw_text)
    extraction_text = _translate_requirement_to_english(raw_text, language)
    translated_deterministic = _deterministic_parse(extraction_text)

    attach_note = ""
    if attachments:
        attach_note = f"\n\nAttachments: {len(attachments)} file(s) attached."
        for a in attachments:
            if isinstance(a, dict):
                attach_note += f"\n- {a.get('filename', 'unnamed')} ({a.get('type', 'unknown')})"

    existing_note = ""
    if existing_requirement:
        existing_note = f"\n\nPrevious requirement context: category={existing_requirement.category}, product={existing_requirement.product_type}"

    original_note = ""
    if extraction_text != raw_text:
        original_note = f"\n\nOriginal customer message ({language}):\n{raw_text}"
    user_prompt = (
        f"Customer message:\n{extraction_text}{attach_note}{existing_note}{original_note}\n\n"
        f"Extract and structure all requirement fields. Original language: {language}"
    )

    try:
        result = llm_complete_json("requirement_structuring", REQUIREMENT_STRUCTURING_SYSTEM, user_prompt)
    except Exception:
        result = {}

    if not result or result.get("confidence", 0) < 0.3:
        result = {}
        result["confidence"] = 0.5
    else:
        result = dict(result)

    result = _merge_fill_missing(result, translated_deterministic)
    result = _merge_fill_missing(result, raw_deterministic)
    for field in AUTHORITATIVE_DETERMINISTIC_FIELDS:
        if _has_meaningful_value(raw_deterministic.get(field)):
            result[field] = raw_deterministic[field]

    result["language"] = language
    if extraction_text != raw_text:
        extra = result.get("extra") if isinstance(result.get("extra"), dict) else {}
        extra["translated_text"] = extraction_text
        result["extra"] = extra

    if existing_requirement:
        for field in BuyerRequirement.model_fields:
            if field not in result and getattr(existing_requirement, field, None):
                existing_val = getattr(existing_requirement, field)
                if existing_val is not None and existing_val != "" and existing_val != []:
                    result[field] = existing_val

    missing_raw = result.pop("missing_fields", [])

    safe_data = {k: v for k, v in result.items() if k in BuyerRequirement.model_fields and k not in ("missing_fields", "project_id", "raw_text")}
    safe_data = _coerce_nulls(safe_data, BuyerRequirement)
    safe_data = _coerce_field_shapes(safe_data, BuyerRequirement)
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
