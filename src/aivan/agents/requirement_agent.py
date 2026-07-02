from __future__ import annotations
import json

from pydantic import BaseModel
from aivan.schemas.requirement import BuyerRequirement, MissingField
from aivan.llm.gateway import llm_complete_json
from aivan.llm.policy import ExternalModelApiRequiresApprovalError
from aivan.llm.prompts import REQUIREMENT_STRUCTURING_SYSTEM
from aivan.utils.language import detect_language
from aivan.integrations.language_skill import apply_to_requirement, canonicalize_rfq


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
    """Normalize common malformed LLM field shapes before Pydantic validation."""
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

def _deterministic_parse(raw_text: str) -> dict:
    """Fallback: extract only numeric/enumerable RAW EVIDENCE without any LLM.

    This deliberately does NOT canonicalize business semantics. It never maps a
    product surface form to a canonical SKU/category, and it never maps a place
    surface form to a canonical destination (no city/port alias tables). Those
    canonical facts require an authoritative source (language-skill, resolvers,
    giraffe-db, or human confirmation) — raw text alone is not authority.
    """
    import re
    result: dict = {}
    text_lower = raw_text.lower()

    qty_match = re.search(r'(\d[\d,]*)\s*(?:件|pcs|pieces|units)', raw_text)
    if qty_match:
        result["quantity"] = int(qty_match.group(1).replace(",", ""))

    gsm_match = re.search(r'(\d+)\s*gsm', text_lower)
    if gsm_match:
        result["gsm"] = int(gsm_match.group(1))

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
    source_channel: str | None = None,
) -> BuyerRequirement:
    """Structure a customer requirement using LLM, with deterministic fallback.

    When the shared giraffe-language-skill service is enabled
    (``AIVAN_LANGUAGE_SKILL_ENABLED=true``), the raw message is first
    canonicalized there. Its deterministic extraction is authoritative for the
    explicit business facts a small local LLM tends to drop (quantity,
    destination, lead time, product), and the full provenance chain is recorded
    under ``requirement.extra["language_skill"]``. The call is fail-soft.
    """
    language = detect_language(raw_text)

    # Canonicalize inbound RFQ via the language skill (no-op when disabled).
    canonicalization = canonicalize_rfq(
        raw_text, source_channel=source_channel, tenant_id=project_id or "default"
    )

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

    llm_used = True
    try:
        result = llm_complete_json("requirement_structuring", REQUIREMENT_STRUCTURING_SYSTEM, user_prompt)
    except ExternalModelApiRequiresApprovalError:
        # External model disabled without approval: continue in private-domain
        # baseline (reduced strength), never a silent cloud fallback.
        result = {}
    except Exception:
        result = {}

    if not result or result.get("confidence", 0) < 0.3:
        result = _deterministic_parse(raw_text)
        result["language"] = language
        result["confidence"] = 0.5
        llm_used = False

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

    # Record provenance for the fields the structuring layer produced. The RFQ
    # structuring model's *structured* output is provisional canonical evidence
    # (llm_structured); a pure deterministic-regex fallback is raw_text_only and
    # is NOT authoritative for canonical product/destination.
    field_source = "llm_structured" if llm_used else "raw_text_only"
    sources: dict[str, str] = {}
    for field in ("product_type", "category", "destination", "quantity",
                  "delivery_days", "color", "fabric_material"):
        if safe_data.get(field) not in (None, "", []):
            sources[field] = field_source
    req.extra["field_sources"] = sources

    # Overlay the language-skill canonicalization (authoritative for explicit
    # business facts) before computing missing fields, so clarification only
    # asks for what is genuinely absent.
    if canonicalization:
        apply_to_requirement(req, canonicalization)
        _record_language_skill_sources(req, canonicalization)

    req.missing_fields = _detect_missing_fields(req)

    # Category selects which required-field template applies. It is inferred only
    # from an authoritative structured category, never from hardcoded keyword ->
    # category business-semantic mappings.
    if not req.category:
        req.category = "general"

    return req


def _record_language_skill_sources(req: BuyerRequirement, canonicalization: dict) -> None:
    """Mark language-skill-provided fields as authoritative in field_sources."""
    structure_data = (canonicalization or {}).get("structure") or {}
    structured = structure_data.get("structured") or {}
    sources = req.extra.setdefault("field_sources", {})
    for src_field, req_attr in {
        "product_name": "product_type",
        "product_category": "category",
        "destination": "destination",
        "quantity": "quantity",
        "lead_time_days": "delivery_days",
    }.items():
        value = structured.get(src_field)
        if value not in (None, "", []):
            sources[req_attr] = "language_skill"
    # Preserve raw evidence spans for confirmation prompts.
    normalize_data = (canonicalization or {}).get("normalize") or {}
    evidence = normalize_data.get("field_evidence") or {}
    if isinstance(evidence, dict):
        if evidence.get("destination"):
            req.extra.setdefault("destination_raw", _evidence_text(evidence["destination"]))
        if evidence.get("product") or evidence.get("product_name"):
            req.extra.setdefault("product_raw", _evidence_text(evidence.get("product") or evidence.get("product_name")))


def _evidence_text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("raw") or value.get("text") or value.get("span") or "")
    if isinstance(value, list) and value:
        return _evidence_text(value[0])
    return str(value or "")
