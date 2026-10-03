"""Supplier selection and pending inquiry draft creation."""

from __future__ import annotations

from sqlalchemy.orm import Session

from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.execution.rfq_user_control import draft_supplier_email
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import GiraffeContext, RFQStrategy, SupplierRoutingDecision


def select_suppliers(
    giraffe: GiraffeContext,
    strategy: RFQStrategy,
) -> SupplierRoutingDecision:
    suppliers = sorted(
        giraffe.suppliers,
        key=lambda supplier: (
            supplier.get("past_performance_score", 0),
            supplier.get("delivery_score", 0),
            supplier.get("quality_score", 0),
        ),
        reverse=True,
    )
    selected = [supplier["supplier_id"] for supplier in suppliers if supplier.get("email")][:5]
    skipped = [supplier["supplier_id"] for supplier in suppliers if not supplier.get("email")]
    return SupplierRoutingDecision(
        selected_supplier_ids=selected,
        skipped_supplier_ids=skipped,
        public_bidding_mode=strategy.public_bidding,
        rationale=(
            "Known suppliers selected first from Giraffe DB context; public bidding is "
            f"{strategy.public_bidding} per strategy."
        ),
    )


def create_supplier_email_drafts(
    project_id: str,
    event: OpenClawEvent,
    requirement: BuyerRequirement,
    strategy: RFQStrategy,
    giraffe: GiraffeContext,
    gltg,
    routing: SupplierRoutingDecision,
    db: Session,
) -> list[str]:
    repo = DraftRepository(db)
    suppliers_by_id = {supplier["supplier_id"]: supplier for supplier in giraffe.suppliers}
    draft_ids = []
    for supplier_id in routing.selected_supplier_ids:
        supplier = suppliers_by_id[supplier_id]
        message_text = draft_supplier_email(requirement, strategy, supplier, gltg)
        draft = repo.create(
            project_id,
            {
                "tenant_id": event.tenant_id or "legacy",
                "conversation_id": event.conversation_id,
                "channel": "email",
                "target_peer_id": supplier.get("email", ""),
                "target_role": "supplier",
                "message_text": message_text,
                "message_type": "text",
                "attachments_json": [],
                "status": "pending_approval",
                "created_by_agent": "aivan_rfq_execution",
                "notes": (
                    "draft_type=supplier_inquiry_email Known supplier: "
                    f"{supplier.get('name', supplier_id)}"
                ),
            },
        )
        draft_ids.append(draft.draft_id)
        ExecutionEventRepository(db).append(
            project_id,
            "PENDING_EMAIL_DRAFT_CREATED",
            f"Supplier inquiry email draft created for {supplier.get('name', supplier_id)}",
            payload={"draft_id": draft.draft_id, "supplier_id": supplier_id},
            actor="aivan_rfq_execution",
        )
    return draft_ids
