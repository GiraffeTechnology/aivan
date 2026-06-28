"""Robust OpenClaw / WeChat invocation endpoint helpers.

OpenClaw (and the WeChat channel behind it) calls AIVAN with a single
free-form turn and expects one structured JSON reply. The heavy RFQ pipeline
(`create_rfq_from_event`) depends on the LLM, giraffe-db and GLTG services, any
of which can be slow or unavailable on the live server. When the pipeline
raised, the OpenClaw agent harness received a non-JSON 500 and surfaced the
generic "Agent couldn't generate a response. Please try again." to the user.

This module makes the invocation path fail-soft: it always extracts the
procurement intent deterministically, attempts to enrich the reply via the full
pipeline within a bounded time, and never raises. The response always conforms
to the OpenClaw skill contract: ``{"status", "output", "artifacts", "trace_id"}``.
"""

from __future__ import annotations

import os
import re
import threading
import uuid

# Keys that different OpenClaw / WeChat adapters use to carry the message text.
# Ordered by preference; the first non-empty string wins.
_TEXT_KEYS = ("user_input", "message", "text", "content", "input", "prompt", "query")

# Nested paths some gateways use, e.g. {"payload": {"text": ...}}.
_NESTED_TEXT_PATHS = (
    ("payload", "text"),
    ("event", "message", "text"),
    ("message", "text"),
    ("body", "content"),
    ("data", "text"),
)

# Destination cities we recognise directly. Keeps extraction robust even when the
# preposition heuristic would grab a verb fragment (e.g. "交货").
_KNOWN_DESTINATIONS = (
    "东京", "大阪", "名古屋", "首尔", "釜山", "上海", "北京", "广州", "深圳",
    "香港", "纽约", "洛杉矶", "芝加哥", "伦敦", "巴黎", "柏林", "汉堡", "鹿特丹",
    "迪拜", "新加坡", "曼谷", "胡志明", "悉尼", "墨尔本", "温哥华", "多伦多",
    "Tokyo", "Osaka", "Seoul", "Shanghai", "New York", "Los Angeles", "Chicago",
    "London", "Paris", "Berlin", "Hamburg", "Rotterdam", "Dubai", "Singapore",
    "Bangkok", "Sydney", "Vancouver", "Toronto",
)

_DEGRADED_NOTE = "正在查询供应商与报价条件，相关数据服务暂未就绪，已记录您的需求，请稍后再试。"

_QUOTE_INTENT_TOKENS = (
    "询价", "报价", "求购", "采购", "比价", "供应商", "下单",
    "quote", "quotation", "rfq", "supplier", "sourcing", "procure", "purchase",
)


def _first_str(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _nested(data: dict, path: tuple[str, ...]) -> object:
    node: object = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def extract_message_text(data: dict) -> str:
    """Pull the user message text from any common OpenClaw/WeChat payload shape."""
    direct = _first_str(*(data.get(key) for key in _TEXT_KEYS))
    if direct:
        return direct
    return _first_str(*(_nested(data, path) for path in _NESTED_TEXT_PATHS))


def normalize_invoke_payload(data: dict) -> tuple[str, str, dict]:
    """Return ``(session_id, user_input, context)`` from a raw invocation body."""
    if not isinstance(data, dict):
        return "", "", {}
    context = data.get("context")
    if not isinstance(context, dict):
        context = {}
    session_id = _first_str(
        data.get("session_id"),
        data.get("sessionId"),
        data.get("conversation_id"),
        context.get("session_id"),
        context.get("conversation_id"),
    )
    user_input = extract_message_text(data)
    return session_id, user_input, context


def extract_rfq_intent(text: str) -> dict:
    """Deterministically extract procurement intent from a free-form message.

    Returns the fields the WeChat acceptance test expects: ``intent``, ``product``,
    ``quantity``, ``delivery_time``, ``destination``. Missing fields are ``None``.
    Pure string logic so it stays correct without the LLM/DB/GLTG dependencies.
    """
    text = text or ""
    lowered = text.lower()

    intent = (
        "supplier_quotation"
        if any(token in text or token in lowered for token in _QUOTE_INTENT_TOKENS)
        else "general_inquiry"
    )

    quantity: int | None = None
    # No trailing \b: Chinese unit chars are word chars, so "1000件格子" has no
    # word boundary after 件 and \b would fail to match the quantity.
    unit_qty = re.search(r"(\d[\d,]*)\s*(件|个|套|条|pcs|pieces|units|pairs)", text, re.IGNORECASE)
    if unit_qty:
        quantity = int(unit_qty.group(1).replace(",", ""))
    else:
        kw_qty = re.search(r"(?:quantity|qty|数量)\D{0,4}(\d[\d,]*)", text, re.IGNORECASE)
        if kw_qty:
            quantity = int(kw_qty.group(1).replace(",", ""))

    product: str | None = None
    if unit_qty:
        tail = text[unit_qty.end():]
        product_match = re.match(r"\s*([^\s,，。;；、!！?？]+)", tail)
        if product_match:
            product = product_match.group(1).strip() or None

    delivery_time: str | None = None
    delivery_match = re.search(r"(\d+)\s*(天|日|周|个月|月|days?|weeks?|months?)\s*(内|以内)?", text, re.IGNORECASE)
    if delivery_match:
        suffix = delivery_match.group(3) or ""
        delivery_time = f"{delivery_match.group(1)}{delivery_match.group(2)}{suffix}"

    destination: str | None = None
    for city in _KNOWN_DESTINATIONS:
        if city in text or city.lower() in lowered:
            destination = city
            break
    if destination is None:
        prep = re.search(
            r"(?:交货?到|交货?|运往|运到|发往|发到|送到|ship\s*to|deliver(?:ed)?\s*to)\s*([^\s,，。;；、]+)",
            text,
            re.IGNORECASE,
        )
        if prep:
            destination = prep.group(1).strip() or None

    return {
        "intent": intent,
        "product": product,
        "quantity": quantity,
        "delivery_time": delivery_time,
        "destination": destination,
    }


def _intent_summary_lines(intent: dict) -> list[str]:
    label = {
        "product": "产品",
        "quantity": "数量",
        "delivery_time": "交期",
        "destination": "目的地",
    }
    lines: list[str] = []
    if intent.get("product"):
        lines.append(f"• {label['product']}：{intent['product']}")
    if intent.get("quantity") is not None:
        lines.append(f"• {label['quantity']}：{intent['quantity']} 件")
    if intent.get("delivery_time"):
        lines.append(f"• {label['delivery_time']}：{intent['delivery_time']}")
    if intent.get("destination"):
        lines.append(f"• {label['destination']}：{intent['destination']}")
    return lines


def degraded_reply_text(intent: dict) -> str:
    """Human-readable acknowledgement when backend dependencies are unavailable."""
    header = "已收到您的询价需求：" if intent.get("intent") == "supplier_quotation" else "已收到您的请求："
    lines = [header, *_intent_summary_lines(intent), "", _DEGRADED_NOTE]
    return "\n".join(lines)


def _invoke_timeout_seconds() -> float:
    try:
        return float(os.environ.get("AIVAN_INVOKE_TIMEOUT_SECONDS", "12"))
    except ValueError:
        return 12.0


def _run_pipeline(text: str, context: dict, session_id: str, result: dict) -> None:
    """Run the full RFQ pipeline on its own DB session. Best-effort enrichment."""
    try:
        from aivan.db.session import get_session_factory
        from aivan.openclaw.event_adapter import parse_openclaw_event
        from aivan.execution.rfq_execution import create_rfq_from_event

        session_factory = get_session_factory()
        db = session_factory()
        try:
            # Carry through project_id / role_context when OpenClaw supplies them:
            # classify_event uses them to attach a reply to its existing project, and
            # is_supplier_reply uses role_context to route supplier replies. Dropping
            # them would misclassify a supplier reply as a brand-new RFQ.
            event_payload = {
                "source": "openclaw",
                "channel": _first_str(context.get("channel")) or "wechat",
                "conversation_id": session_id or "invoke",
                "sender_id": _first_str(context.get("sender_id")) or "wechat-user",
                "message_text": text,
                "message_type": "text",
                "mode": _first_str(context.get("mode")) or "auto",
            }
            project_id = _first_str(context.get("project_id"))
            if project_id:
                event_payload["project_id"] = project_id
            role_context = _first_str(context.get("role_context"))
            if role_context:
                event_payload["role_context"] = role_context
            event = parse_openclaw_event(event_payload)
            rfq = create_rfq_from_event(event, db)
            result["ok"] = True
            result["project_id"] = rfq.project_id
            result["enrichment"] = (rfq.user_control_message or rfq.message or "").strip()
            result["drafts"] = list(rfq.drafts_created or [])
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - pipeline must never break the reply
        result["error"] = f"{type(exc).__name__}: {exc}"


def _build_output(intent: dict, pipeline: dict) -> str:
    header = "已收到您的询价需求：" if intent.get("intent") == "supplier_quotation" else "已收到您的请求："
    lines = [header, *_intent_summary_lines(intent)]

    enrichment = pipeline.get("enrichment")
    if pipeline.get("ok") and enrichment:
        lines.append("")
        lines.append(enrichment)
    elif pipeline.get("ok"):
        lines.append("")
        lines.append("已为您创建采购项目，供应商沟通草稿待您确认。")
    else:
        # Degraded: dependency unavailable or timed out. Acknowledge clearly instead
        # of erroring so the WeChat user always gets a meaningful reply.
        lines.append("")
        lines.append(_DEGRADED_NOTE)

    return "\n".join(line for line in lines if line is not None)


def run_invocation(data: dict) -> dict:
    """Process one OpenClaw/WeChat turn and return an OpenClaw-compatible reply.

    Never raises: dependency failures degrade to a clear acknowledgement.
    """
    trace_id = uuid.uuid4().hex
    session_id, user_input, context = normalize_invoke_payload(data)

    if not user_input:
        return {
            "status": "error",
            "output": "I received the WeChat event but could not extract message text.",
            "artifacts": [],
            "trace_id": trace_id,
        }

    intent = extract_rfq_intent(user_input)

    pipeline: dict = {}
    dry_run = bool(context.get("dry_run"))
    if not dry_run:
        worker = threading.Thread(
            target=_run_pipeline,
            args=(user_input, context, session_id, pipeline),
            daemon=True,
        )
        worker.start()
        worker.join(_invoke_timeout_seconds())
        if worker.is_alive():
            pipeline["error"] = "pipeline timed out"

    output = _build_output(intent, pipeline)
    response = {
        "status": "ok",
        "output": output,
        "artifacts": list(pipeline.get("drafts") or []),
        "trace_id": trace_id,
        "intent": intent,
    }
    if pipeline.get("project_id"):
        response["project_id"] = pipeline["project_id"]
    return response
