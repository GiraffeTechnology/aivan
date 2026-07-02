"""Deterministic, user-facing operator reply renderer.

The IM/operator reply must be deterministic, language-matched, and accurate to
the actual ``action`` — never leaking internal debug fields (``Strategy=``,
``GLTG P50=``, raw ``draft_...`` ids, or ``TBD``). It must claim drafts exist
only when they do, and it must never say "ready for approval" for a blocked
action (PRD §9).
"""

from __future__ import annotations

from aivan.schemas.rfq import RFQExecutionResult


def _is_chinese(result: RFQExecutionResult, language: str) -> bool:
    lang = (language or "").lower()
    if lang.startswith("zh"):
        return True
    if lang.startswith("en"):
        return False
    req = result.requirement or {}
    if req.get("language") == "zh":
        return True
    raw = req.get("raw_text", "") or ""
    return any("一" <= ch <= "鿿" for ch in raw)


def _product_label(req: dict, zh: bool) -> str:
    quality = ""
    extra = req.get("extra") or {}
    if isinstance(extra, dict):
        quality = extra.get("quality_level") or ""
    base = req.get("product_type") or req.get("category") or ""
    if not base:
        base = "产品" if zh else "product"
    if quality and zh:
        prefix = {"high": "高品质", "medium": "中等品质", "low": "低品质"}.get(quality, "")
        return f"{prefix}{base}" if prefix else base
    if quality and not zh:
        return f"{quality}-quality {base}"
    return base


def render_operator_reply(result: RFQExecutionResult, language: str = "") -> str:
    """Render the operator-facing reply for an RFQ execution result."""
    zh = _is_chinese(result, language)
    action = result.action or ""
    req = result.requirement or {}

    # Blocked / confirmation / recovery actions carry a ready operator message.
    if action != "pending_email_approval":
        if result.user_control_message:
            return result.user_control_message
        return _fallback_blocked_message(result, zh)

    # Happy path: RFQ created, supplier drafts pending human approval.
    qty = req.get("quantity")
    unit = req.get("quantity_unit") or ("件" if zh else "pcs")
    dest = req.get("destination") or ""
    days = req.get("delivery_days")
    product = _product_label(req, zh)
    draft_count = len(result.drafts_created or [])

    if zh:
        lines = ["RFQ 已创建，等待人工审批："]
        lines.append(f"- 产品：{product}")
        if qty is not None:
            lines.append(f"- 数量：{qty} {unit}")
        if dest:
            dest_raw = (req.get("extra") or {}).get("destination_raw") if isinstance(req.get("extra"), dict) else None
            lines.append(f"- 目的地：{dest}（原文：{dest_raw}）" if dest_raw else f"- 目的地：{dest}")
        if days is not None:
            lines.append(f"- 目标交期：{days} 天")
        if draft_count:
            lines.append(f"- 草稿数量：{draft_count}")
        lines.append("- 当前状态：供应商询价草稿等待人工审批")
        lines.append("")
        lines.append("注意：供应商邮件尚未发送，仍需人工审批后才会发送。")
        return "\n".join(lines)

    lines = ["RFQ created, pending human approval:"]
    lines.append(f"- Product: {product}")
    if qty is not None:
        lines.append(f"- Quantity: {qty} {unit}")
    if dest:
        lines.append(f"- Destination: {dest}")
    if days is not None:
        lines.append(f"- Target delivery: {days} days")
    if draft_count:
        lines.append(f"- Draft count: {draft_count}")
    lines.append("")
    lines.append("Note: supplier emails have NOT been sent; human approval is still required before sending.")
    return "\n".join(lines)


def _fallback_blocked_message(result: RFQExecutionResult, zh: bool) -> str:
    if zh:
        return (
            "RFQ 已记录，但尚未满足执行条件，需人工确认后 AIVAN 才会继续。"
            "供应商邮件尚未发送。"
        )
    return (
        "RFQ recorded, but execution prerequisites are not yet met; AIVAN needs "
        "human confirmation before continuing. No supplier emails were sent."
    )
