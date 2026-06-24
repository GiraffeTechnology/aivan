#!/usr/bin/env python3
"""AIVAN private-domain RFQ execution E2E.

Verifies:
- OpenClaw user IM event ingestion
- LLM/mock strategy interpretation
- Giraffe DB supplier/context lookup
- GLTG lead-time simulation
- RFQ/project creation
- Pending supplier email drafts
- User IM approval notification
- No unapproved outbound supplier email
"""
from __future__ import annotations

import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_DB_URL", "sqlite:///./data/aivan_private_domain_rfq_e2e.db")
os.environ.setdefault("AIVAN_REQUIRE_HUMAN_APPROVAL", "true")

from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.session import db_session, init_db
from aivan.execution.rfq_execution import create_rfq_from_event
from aivan.openclaw.event_adapter import parse_openclaw_event


def main() -> None:
    print("=" * 72)
    print("AIVAN PRIVATE-DOMAIN RFQ E2E")
    print("=" * 72)

    os.makedirs("data", exist_ok=True)
    init_db()

    conversation_id = f"private_domain_rfq_{uuid4().hex[:8]}"
    event_data = {
        "source": "openclaw",
        "channel": "wechat",
        "channel_account_id": "sales-user-im",
        "conversation_id": conversation_id,
        "message_id": f"msg_{uuid4().hex[:8]}",
        "sender_id": "user_001",
        "sender_display_name": "Sales User",
        "message_text": "这个客户很急，先问熟悉供应商。帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华。",
        "message_type": "text",
        "attachments": [],
        "role_context": "user",
        "mode": "command",
    }

    print("\n1. Ingest OpenClaw user IM event")
    with db_session() as db:
        result = create_rfq_from_event(parse_openclaw_event(event_data), db)
        project_id = result.project_id
        print(f"   project_id: {project_id}")
        print(f"   event_type: {result.event_type}")
        print(f"   strategy  : {result.strategy.model_dump()}")
        print(f"   GLTG P80  : {result.gltg_simulation.p80_days} days")

        assert result.event_type == "user_command"
        assert result.strategy.priority == "speed"
        assert result.strategy.supplier_scope == "known_suppliers_first"
        assert result.giraffe_context.suppliers, "Expected Giraffe DB supplier context"
        assert result.gltg_simulation.p80_days > 0, "Expected GLTG P80 lead-time output"
        assert result.drafts_created, "Expected supplier email drafts"

        drafts = DraftRepository(db).list_for_project(project_id)
        supplier_email_drafts = [
            draft
            for draft in drafts
            if draft.target_role == "supplier" and draft.channel == "email"
        ]
        user_notifications = [
            draft
            for draft in drafts
            if draft.target_role == "user" and "draft_type=approval_request_im" in (draft.notes or "")
        ]
        events = ExecutionEventRepository(db).list_for_project(project_id)

        print("\n2. Verify private-domain RFQ artifacts")
        print(f"   supplier email drafts: {len(supplier_email_drafts)}")
        print(f"   user IM notifications: {len(user_notifications)}")
        print(f"   audit events          : {len(events)}")

        assert supplier_email_drafts, "Expected pending supplier email drafts"
        assert all(draft.status == "pending_approval" for draft in supplier_email_drafts)
        assert user_notifications, "Expected user IM approval notification"
        assert user_notifications[0].status == "sent"
        assert any(event.event_type == "GIRAFFE_CONTEXT_LOOKUP" for event in events)
        assert any(event.event_type == "GLTG_SIMULATION_CREATED" for event in events)
        assert any(event.event_type == "USER_CONTROL_APPROVAL_REQUESTED" for event in events)
        assert all(draft.sent_at is None for draft in supplier_email_drafts), "Supplier emails must not send before approval"

    print("\n3. No unapproved outbound supplier email: PASS")
    print("=" * 72)
    print("AIVAN PRIVATE-DOMAIN RFQ E2E: PASS")
    print("=" * 72)


if __name__ == "__main__":
    main()
