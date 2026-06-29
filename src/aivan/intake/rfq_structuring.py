from __future__ import annotations

import re

TRACE_PREFIX_RE = re.compile(r"^\s*(?:AIVANPR18OK|AIVAN-TRACE-[^\s，,]+|AIVAN-OLLAMA-[^\s，,]+|AIVAN-OLLAMA-NATIVE)\s*", re.I)
TEST_PREFIX_RE = re.compile(r"^\s*(?:INTAKE|TEST)-\d+\s*", re.I)
QUANTITY_RE = re.compile(r"(?P<quantity>\d{1,9})\s*(?P<unit>件|个|pcs?|pieces?|套|箱|双|kg|公斤|吨)?", re.I)
LEAD_TIME_RE = re.compile(r"(?P<days>\d{1,4})\s*(?:天|days?|d)\s*(?:交|交货|内)?", re.I)
DESTINATION_PATTERNS = [
    re.compile(r"(?:交|到|发到|送到)\s*(?P<dest>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z\s-]{1,30})"),
    re.compile(r"(?:to|deliver(?:y)? to|ship to)\s+(?P<dest>[A-Za-z][A-Za-z\s-]{1,40})", re.I),
]
DEADLINE_RE = re.compile(r"(?P<deadline>\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)")

PRODUCT_CATEGORIES = [
    ("t-shirt", ["t恤", "T恤", "tee", "t-shirt", "shirt tee"]),
    ("shirt", ["衬衫", "shirt"]),
    ("bolts", ["bolt", "螺栓"]),
]
MATERIALS = ["纯棉", "棉", "涤纶", "真丝", "亚麻", "不锈钢", "铝", "steel", "cotton", "polyester"]
QUALITY_LEVELS = ["高品质", "高质量", "中高端", "低价", "便宜", "premium", "high quality", "standard"]
COLORS = ["红色", "蓝色", "黑色", "白色", "绿色", "黄色", "灰色", "red", "blue", "black", "white", "green", "yellow", "gray", "grey"]
SIZE_RE = re.compile(r"(?:尺码|尺寸|size)[:：]?\s*(?P<size>[A-Za-z0-9/,\-\s]+)", re.I)

FILLER_TOKENS = [
    "帮我询价",
    "询价",
    "报价",
    "采购",
    "这个也帮我问一下",
    "也帮我问一下",
    "也问一下",
    "帮我",
    "这个",
    "please quote",
    "quote",
    "rfq",
]


def structure_inquiry_text(raw_text: str) -> dict:
    text = strip_trace_prefix(raw_text or "").strip()
    result: dict = {
        "notes": text,
        "language": "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en",
    }
    if not text:
        return result

    quantity_match = QUANTITY_RE.search(text)
    if quantity_match:
        result["quantity"] = int(quantity_match.group("quantity"))
        result["quantity_unit"] = quantity_match.group("unit") or "件"

    lead_match = LEAD_TIME_RE.search(text)
    if lead_match:
        result["lead_time_days"] = int(lead_match.group("days"))

    deadline_match = DEADLINE_RE.search(text)
    if deadline_match:
        result["delivery_deadline"] = deadline_match.group("deadline")

    destination = _extract_destination(text)
    if destination:
        result["destination"] = destination

    quality = _first_present(text, QUALITY_LEVELS)
    if quality:
        result["quality_level"] = quality

    material = _first_present(text, MATERIALS)
    if material:
        result["material"] = material

    color = _first_present(text, COLORS)
    if color:
        result["color"] = color

    size_match = SIZE_RE.search(text)
    if size_match:
        result["size"] = _trim_phrase(size_match.group("size"))

    product_name = _extract_product_name(text, result)
    if product_name:
        result["product_name"] = product_name

    category = _category_for(product_name or text)
    if category:
        result["product_category"] = category

    return result


def strip_trace_prefix(raw_text: str) -> str:
    text = raw_text or ""
    previous = None
    while text != previous:
        previous = text
        text = TRACE_PREFIX_RE.sub("", text)
        text = TEST_PREFIX_RE.sub("", text)
    return text.strip()


def normalized_product(structured: dict) -> str:
    product = str(structured.get("product_name") or "").strip()
    if product:
        return product.lower()
    category = str(structured.get("product_category") or "").strip()
    return category.lower()


def _extract_destination(text: str) -> str:
    for pattern in DESTINATION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = _trim_phrase(match.group("dest"))
        value = re.split(r"[，,。.;；]|\d+\s*(?:件|个|pcs?|天|days?)|高品质|高质量", value, maxsplit=1, flags=re.I)[0]
        return _trim_phrase(value)

    compact = re.sub(r"\s+", "", text)
    match = re.search(r"\d+\s*天(?P<dest>[\u4e00-\u9fff]{2,8})(?:[，,。.;；]|$)", compact)
    if match:
        return _trim_phrase(match.group("dest"))
    return ""


def _extract_product_name(text: str, fields: dict) -> str:
    working = strip_trace_prefix(text)
    working = re.sub(r"^\s*(INTAKE-\d+|TEST-\d+)\s*", "", working, flags=re.I)
    for token in FILLER_TOKENS:
        working = re.sub(re.escape(token), "", working, flags=re.I)
    working = QUANTITY_RE.sub("", working, count=1)
    working = LEAD_TIME_RE.sub("", working, count=1)
    working = DEADLINE_RE.sub("", working, count=1)
    for value in [
        fields.get("destination"),
        fields.get("quality_level"),
        fields.get("color"),
        fields.get("size"),
    ]:
        if value:
            working = working.replace(str(value), "")
    working = re.sub(r"(?:交|到|发到|送到|to|deliver(?:y)? to|ship to)", "", working, flags=re.I)
    pieces = [_trim_phrase(piece) for piece in re.split(r"[，,。.;；]", working)]
    pieces = [piece for piece in pieces if piece and not piece.isdigit()]
    if pieces:
        candidate = max(pieces, key=len)
        return _trim_phrase(candidate)
    return ""


def _category_for(text: str) -> str:
    lowered = (text or "").lower()
    for category, tokens in PRODUCT_CATEGORIES:
        if any(token.lower() in lowered for token in tokens):
            return category
    return ""


def _first_present(text: str, values: list[str]) -> str:
    lowered = text.lower()
    for value in values:
        if value.lower() in lowered:
            return value
    return ""


def _trim_phrase(value: str) -> str:
    return re.sub(r"^[\s:：,，。.;；]+|[\s:：,，。.;；]+$", "", value or "")
