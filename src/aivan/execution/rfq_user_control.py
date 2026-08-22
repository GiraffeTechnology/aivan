from __future__ import annotations

from sqlalchemy.orm import Session

from aivan.db.repositories.draft_repo import DraftRepository
from aivan.execution.channel_policy import USER_CONTROL_CHANNELS, normalize_channel
from aivan.llm.gateway import llm_complete_json
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import RFQStrategy, SupplierRoutingDecision
from aivan.utils.env import env_bool

DRAFT_SYSTEM = """
You draft concise business email text from AIVAN-provided requirement, strategy,
supplier, and GLTG context. Do not invent facts. Return JSON only.
"""


def send_user_control_notification(
    project_id: str,
    event: OpenClawEvent,
    message_text: str,
    db: Session,
) -> dict:
    channel, target_peer_id, owner_resolved, reason = user_control_channel_and_target(
        event, db
    )
    draft = DraftRepository(db).create(
        project_id,
        {
            "tenant_id": event.tenant_id or "legacy",
            "conversation_id": event.conversation_id,
            "channel": channel,
            "target_peer_id": target_peer_id,
            "target_role": "user",
            "message_text": message_text,
            "message_type": "text",
            "attachments_json": [],
            # Owner resolution is routing evidence, never outbound consent.
            "status": "pending_approval",
            "created_by_agent": "aivan_user_control",
            "notes": (
                "draft_type=approval_request_im "
                f"owner_resolved={str(owner_resolved).lower()} {reason} "
                "outbound_authorization=required"
            ),
        },
    )
    return {
        "draft_id": draft.draft_id,
        "sent": False,
        "message_id": "",
        "owner_resolved": owner_resolved,
        "error": (
            "explicit outbound authorization required"
            if owner_resolved
            else "owner resolution and explicit outbound authorization required"
        ),
    }


def user_control_channel_and_target(
    event: OpenClawEvent, db: Session
) -> tuple[str, str, bool, str]:
    role = (event.role_context or "").lower()
    normalized_channel = normalize_channel(event.channel)
    notification_channel = (
        event.channel if normalized_channel in USER_CONTROL_CHANNELS else "im"
    )
    authenticated_actor_id = event.authenticated_actor_id or ""
    if role in {"user", "owner", "operator", "sales", "salesperson"} or event.mode in {
        "user",
        "command",
    }:
        if authenticated_actor_id:
            return (
                notification_channel or "im",
                authenticated_actor_id,
                True,
                "verified_user_sender",
            )
    if authenticated_actor_id:
        return (
            notification_channel or "im",
            authenticated_actor_id,
            True,
            "verified_actor_id",
        )
    owner_user_id = owner_user_id_for_event(event, db)
    if owner_user_id:
        channel = event.channel if normalized_channel in USER_CONTROL_CHANNELS else "im"
        return channel or "im", owner_user_id, True, "verified_account_owner"
    return "internal", "owner_resolution_required", False, "owner_resolution_required"


def owner_user_id_for_event(event: OpenClawEvent, db: Session) -> str:
    if not event.channel_account_id:
        return ""
    from aivan.db.models.account import OpenClawAccountRecord

    account = (
        db.query(OpenClawAccountRecord)
        .filter(
            OpenClawAccountRecord.channel == event.channel,
            OpenClawAccountRecord.channel_account_id == event.channel_account_id,
            OpenClawAccountRecord.tenant_id == (event.tenant_id or "legacy"),
            OpenClawAccountRecord.status == "connected",
        )
        .first()
    )
    return account.owner_user_id if account and account.owner_user_id else ""


def draft_supplier_email(
    requirement: BuyerRequirement,
    strategy: RFQStrategy,
    supplier: dict,
    gltg,
) -> str:
    schema_hint = {"subject": "", "message_text": ""}
    user_prompt = {
        "supplier": supplier,
        "requirement": requirement.model_dump(),
        "strategy": strategy.model_dump(),
        "gltg": gltg.model_dump(),
    }
    raw = {}
    if env_bool("AIVAN_SUPPLIER_DRAFT_LLM_ENABLED"):
        try:
            raw = llm_complete_json(
                "aivan_supplier_email_draft",
                DRAFT_SYSTEM,
                str(user_prompt),
                schema_hint,
            )
        except Exception:
            raw = {}
    if raw.get("message_text"):
        return raw["message_text"]
    subject = (
        f"RFQ: {requirement.quantity or 'TBD'} "
        f"{requirement.product_type or requirement.category or 'Products'} "
        f"for Delivery to {requirement.destination or 'TBD'} Within "
        f"{requirement.delivery_days or 'TBD'} Days"
    )
    lines = [
        f"Subject: {subject}",
        "",
        f"Dear {supplier.get('name', 'Supplier')},",
        "",
        "We are preparing an RFQ and would like your quotation for the following requirement:",
        f"- Product: {requirement.product_type or requirement.category or 'product'}",
        f"- Quantity: {requirement.quantity or 'TBD'} {requirement.quantity_unit}",
        f"- Material/spec: {requirement.fabric_material or requirement.material_spec or 'TBD'}",
        f"- Color/finish: {requirement.color or requirement.surface_finish or 'TBD'}",
        f"- Destination: {requirement.destination or 'TBD'}",
        f"- Target delivery: {requirement.delivery_days or 'TBD'} days",
        f"- Lead-time confidence requested: {strategy.lead_time_confidence}",
        "",
        "Please include the following in your quotation:",
        "- Unit price",
        "- Total price",
        "- MOQ",
        "- Production capacity",
        "- Lead time",
        "- Earliest shipment date",
        "- Payment terms",
        "- Incoterms / trade terms",
        "- Packaging information",
        "- Validity period of quotation",
        "- Any risks or constraints",
        "",
        "This inquiry is subject to buyer review and final approval.",
        "",
        "Best regards,",
        "AIVAN",
    ]
    return "\n".join(lines)


def _should_use_chinese_user_message(requirement: BuyerRequirement) -> bool:
    return requirement.language == "zh" or any(
        "\u4e00" <= char <= "\u9fff" for char in requirement.raw_text
    )


def _risk_label_for_user(risk_level: str) -> str:
    labels = {
        "low": "低",
        "medium": "中",
        "high": "高",
        "critical": "严重",
        "unknown": "未知",
    }
    return labels.get((risk_level or "unknown").lower(), risk_level or "未知")


def build_user_control_message(
    requirement: BuyerRequirement,
    strategy: RFQStrategy,
    gltg,
    routing: SupplierRoutingDecision,
    drafts_created: list[str],
) -> str:
    if _should_use_chinese_user_message(requirement):
        deadline = (
            f"目标交期 {requirement.delivery_days} 天"
            if requirement.delivery_days
            else "目标交期待确认"
        )
        return (
            f"RFQ 已创建，等待人工审批：{requirement.quantity or 'TBD'} "
            f"{requirement.quantity_unit} "
            f"{requirement.product_type or requirement.category or 'product'}，"
            f"目的地 {requirement.destination or 'TBD'}，{deadline}。"
            f"策略={strategy.priority}/{strategy.supplier_scope}，"
            f"GLTG {strategy.lead_time_confidence}={gltg.selected_confidence_days} 天，"
            f"交期风险={_risk_label_for_user(gltg.deadline_risk_level)}。"
            f"已生成 {len(routing.selected_supplier_ids)} 封供应商邮件草稿，"
            f"仍需人工审批后才会发送：{', '.join(drafts_created)}。"
        )
    return (
        f"RFQ ready for approval: {requirement.quantity or 'TBD'} "
        f"{requirement.quantity_unit} {requirement.color} "
        f"{requirement.product_type or requirement.category} to "
        f"{requirement.destination or 'TBD'}. "
        f"Strategy={strategy.priority}/{strategy.supplier_scope}, "
        f"GLTG {strategy.lead_time_confidence}={gltg.selected_confidence_days} days, "
        f"deadline risk={gltg.deadline_risk_level}. "
        f"{len(routing.selected_supplier_ids)} supplier email drafts are pending "
        f"approval: {', '.join(drafts_created)}."
    )
