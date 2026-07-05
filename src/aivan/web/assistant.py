"""Deterministic trade-assistant behavior for the myaivan Web UI.

The web assistant identifies what kind of business message the user pasted,
summarizes the explicit facts it can extract deterministically, and drafts
channel-appropriate outbound replies for human review. It never sends
anything itself, and it respects the private-domain language boundary: raw
non-English business text is not locally extracted — the assistant asks for
canonicalization / operator confirmation instead (matching AIVAN core).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from aivan.utils.language import is_chinese

IM_CHANNELS = frozenset({"wechat", "whatsapp", "line", "wangwang"})
CHANNELS = frozenset({"email", "manual"} | IM_CHANNELS)

# Commercial-commitment signals → medium/high risk (PRD §16.3).
_HIGH_RISK_PATTERNS = [
    (re.compile(r"order\s+confirm|confirm\s+the\s+order|订单确认|确认订单", re.I), "order confirmation"),
    (re.compile(r"refund|compensat|赔偿|退款", re.I), "refund/compensation"),
    (re.compile(r"legal|contract\s+commit|法律|合同承诺", re.I), "legal commitment"),
    (re.compile(r"exclusive|独家", re.I), "exclusive commitment"),
]
_MEDIUM_RISK_PATTERNS = [
    (re.compile(r"(?:usd|\$|¥|eur|rmb)\s*[\d.,]+|price|单价|报价|quotation", re.I), "price"),
    (re.compile(r"\d+\s*(?:days?|天)|lead\s*time|delivery\s+date|交期|交货", re.I), "lead time / delivery date"),
    (re.compile(r"payment\s+terms?|t/t|l/c|付款", re.I), "payment terms"),
    (re.compile(r"quality\s+(?:commit|guarantee)|质量承诺|保证", re.I), "quality commitment"),
]


@dataclass
class MessageAnalysis:
    message_kind: str  # buyer_inquiry | supplier_quote | follow_up | general | unclear
    language: str
    summary: str
    extracted: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)
    needs_canonicalization: bool = False
    suggest_reply: bool = False


def _extract_facts(text: str) -> dict:
    """Deterministic extraction of explicit facts from English business text."""
    facts: dict = {}
    qty = re.search(r"([\d][\d,]{2,})\s*(?:pcs|pieces|units|sets)?", text, re.I)
    if qty:
        try:
            facts["quantity"] = int(qty.group(1).replace(",", ""))
        except ValueError:
            pass
    price = re.search(r"(?:usd|\$|eur)\s*([\d]+(?:\.[\d]+)?)", text, re.I)
    if price:
        facts["unit_price"] = float(price.group(1))
    days = re.search(r"(\d+)\s*days?", text, re.I)
    if days:
        facts["lead_time_days"] = int(days.group(1))
    moq = re.search(r"moq[:\s]*([\d][\d,]*)", text, re.I)
    if moq:
        facts["moq"] = int(moq.group(1).replace(",", ""))
    dest = re.search(r"(?:to|deliver(?:y|ed)?\s+to|destination[:\s]+)\s+([A-Z][A-Za-z ]{2,30}?)(?:[,.;\n]|$| within| in )", text)
    if dest:
        facts["destination"] = dest.group(1).strip()
    return facts


def classify_message(text: str) -> str:
    t = text.lower()
    if not t.strip():
        return "unclear"
    supplier_signals = ("we can offer", "our price", "quote", "quotation", "moq", "报价", "我们可以", "供货")
    buyer_signals = ("inquiry", "need", "looking for", "rfq", "询价", "求购", "采购", "please quote", "quote for")
    followup_signals = ("follow up", "following up", "any update", "reminder", "跟进", "进展")
    if any(s in t for s in followup_signals):
        return "follow_up"
    # Supplier-quote signals win when a price/MOQ is stated.
    if any(s in t for s in supplier_signals) and re.search(r"(?:usd|\$|¥)\s*[\d.]+|moq", t):
        return "supplier_quote"
    if any(s in t for s in buyer_signals):
        return "buyer_inquiry"
    if any(s in t for s in supplier_signals):
        return "supplier_quote"
    return "general"


def analyze_message(text: str) -> MessageAnalysis:
    language = "zh" if is_chinese(text) else "en"
    kind = classify_message(text)

    if language != "en":
        # Language boundary: do not run local extraction over raw non-English
        # business text. Ask for canonicalization / confirmation instead.
        return MessageAnalysis(
            message_kind=kind,
            language=language,
            summary=(
                "我收到了这条业务消息。为保证信息准确，非英文业务内容需要先经过语言标准化"
                "（giraffe-language-skill）或由你确认关键信息（产品、数量、目的地、交期）后再处理。"
                "请确认关键信息，或直接告诉我下一步怎么处理。"
            ),
            needs_canonicalization=True,
            suggest_reply=False,
        )

    facts = _extract_facts(text)
    missing = []
    if kind in ("buyer_inquiry", "supplier_quote"):
        for key, label in (
            ("quantity", "quantity"),
            ("destination", "destination"),
            ("lead_time_days", "lead time"),
        ):
            if key not in facts:
                missing.append(label)

    kind_labels = {
        "buyer_inquiry": "a buyer inquiry",
        "supplier_quote": "a supplier quote",
        "follow_up": "a follow-up message",
        "general": "a general business message",
        "unclear": "a message I could not classify",
    }
    parts = [f"I read this as {kind_labels[kind]}."]
    if facts:
        rendered = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in facts.items())
        parts.append(f"Extracted: {rendered}.")
    if missing:
        parts.append(f"Missing: {', '.join(missing)}.")
    if kind in ("buyer_inquiry", "supplier_quote", "follow_up"):
        parts.append("Want me to draft a reply? Tell me the target channel (email / WeChat / WhatsApp / LINE / Wangwang).")

    return MessageAnalysis(
        message_kind=kind,
        language=language,
        summary=" ".join(parts),
        extracted=facts,
        missing=missing,
        suggest_reply=kind in ("buyer_inquiry", "supplier_quote", "follow_up"),
    )


def assess_risk(body: str) -> tuple[str, list[str]]:
    """Return (risk_level, risk_notes) for a generated outbound body."""
    notes: list[str] = []
    level = "low"
    for pattern, label in _MEDIUM_RISK_PATTERNS:
        if pattern.search(body):
            notes.append(label)
            level = "medium"
    for pattern, label in _HIGH_RISK_PATTERNS:
        if pattern.search(body):
            notes.append(label)
            level = "high"
    if notes:
        notes.insert(0, "This draft contains commercial terms. Please confirm before sending.")
    return level, notes


def generate_draft_body(channel: str, purpose: str, context_text: str, analysis: MessageAnalysis | None = None) -> str:
    """Deterministic, channel-appropriate outbound draft.

    Email: formal and complete. IM channels: concise. Never fabricates facts —
    unknown values stay as explicit placeholders for the user to fill in.
    """
    facts = (analysis.extracted if analysis else {}) or {}
    qty = facts.get("quantity", "[quantity]")
    dest = facts.get("destination", "[destination]")
    lead = facts.get("lead_time_days", "[lead time]")

    if channel == "email":
        return (
            f"Subject: Re: {purpose}\n\n"
            "Dear partner,\n\n"
            f"Thank you for your message. We confirm receipt of your {purpose}.\n"
            f"Quantity: {qty}\n"
            f"Destination: {dest}\n"
            f"Requested lead time: {lead} days\n\n"
            "Could you please confirm the product specification, packaging requirements, "
            "and target unit price so we can proceed with an accurate quotation?\n\n"
            "Best regards,\nAIVAN (on behalf of the sales team)"
        )
    # Concise IM style for wechat / whatsapp / line / wangwang / manual.
    return (
        f"Thanks for the {purpose}. Noted: quantity {qty}, destination {dest}, "
        f"lead time {lead} days. Could you confirm the product spec, packaging, "
        "and target price? We will revert with a quotation right after."
    )
