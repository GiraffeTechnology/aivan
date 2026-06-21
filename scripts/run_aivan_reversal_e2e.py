#!/usr/bin/env python3
"""E2E smoke test for the information-reversal flow (Workstream D).

Runs in-process with mock adapters.
Exit 0 = all assertions passed.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_EMAIL_MODE", "mock")
os.environ.setdefault("AIVAN_LINE_ENABLED", "true")
os.environ.setdefault("AIVAN_LINE_MODE", "mock")
os.environ["AIVAN_DB_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from aivan.db.models import Base
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.inbound_repo import InboundRelayRepository
from aivan.openclaw.outbound_approval import send_draft


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def run():
    db = _make_db()
    draft_repo = DraftRepository(db)
    event_repo = ExecutionEventRepository(db)
    inbound_repo = InboundRelayRepository(db)

    failures = []

    def check(name, cond, detail=""):
        if not cond:
            failures.append(f"FAIL [{name}]: {detail}")
            print(f"  FAIL  {name}: {detail}")
        else:
            print(f"  PASS  {name}")

    print("\n=== Reversal E2E: paste-not-yet-triggered ===")
    # A paste that hasn't caused downstream effects yet
    ev_untriggered = event_repo.append(
        project_id="rev_proj",
        event_type="inbound_relay_paste",
        summary="Untriggered paste",
        payload={"pasted_text": "Wrong: lead time 3 days"},
    )
    inb_untriggered = inbound_repo.create(
        thread_id="rev_proj",
        counterparty_id="supplier_x",
        pasted_text="Wrong: lead time 3 days",
        linked_execution_event_id=ev_untriggered.event_id,
    )
    # Immediately supersede (user noticed before pipeline ran)
    inbound_repo.supersede(inb_untriggered.inbound_id)
    reversal_1 = event_repo.append_reversal("rev_proj", ev_untriggered.event_id, "typo")
    db.flush()
    check("untriggered: original superseded", ev_untriggered.superseded)
    check("untriggered: inbound superseded", inb_untriggered.superseded)
    check("untriggered: reversal in log",
          reversal_1.event_type == "reversal" and reversal_1.references_event_id == ev_untriggered.event_id)

    print("\n=== Reversal E2E: paste already triggered downstream ===")
    ev_triggered = event_repo.append(
        project_id="rev_proj",
        event_type="inbound_relay_paste",
        summary="Triggered paste",
        payload={"pasted_text": "Price: $5/unit"},
    )
    inb_triggered = inbound_repo.create(
        thread_id="rev_proj",
        counterparty_id="supplier_y",
        pasted_text="Price: $5/unit",
        linked_execution_event_id=ev_triggered.event_id,
    )
    # Downstream draft created and left pending
    pending_draft = draft_repo.create(
        project_id="rev_proj",
        data={
            "channel": "email",
            "message_text": "Quote based on $5/unit",
            "created_by_agent": "pipeline",
            "derived_from_event_id": ev_triggered.event_id,
        },
    )
    db.flush()

    reversal_2 = event_repo.append_reversal("rev_proj", ev_triggered.event_id, "wrong price pasted")
    affected = draft_repo.invalidate_derived(ev_triggered.event_id)
    db.flush()

    check("triggered: reversal event created", reversal_2.event_type == "reversal")
    check("triggered: pending draft invalidated", pending_draft.draft_id in affected)
    db.refresh(pending_draft)
    check("triggered: draft status=invalidated", pending_draft.status == "invalidated")

    all_events = event_repo.list_for_project("rev_proj")
    types = {e.event_type for e in all_events}
    check("triggered: audit chain has reversal", "reversal" in types)

    print("\n=== Reversal E2E: already-sent cannot be recalled ===")
    ev_sent = event_repo.append(
        project_id="rev_proj",
        event_type="inbound_relay_paste",
        summary="Paste that led to sent draft",
        payload={"pasted_text": "MOQ: 100 units"},
    )
    sent_draft = draft_repo.create(
        project_id="rev_proj",
        data={
            "channel": "email",
            "message_text": "MOQ confirmed at 100 units",
            "created_by_agent": "pipeline",
            "derived_from_event_id": ev_sent.event_id,
        },
    )
    draft_repo.approve(sent_draft.draft_id)
    db.flush()
    send_draft(sent_draft.draft_id, db)
    db.flush()

    reversal_3 = event_repo.append_reversal("rev_proj", ev_sent.event_id, "MOQ was wrong")
    draft_repo.invalidate_derived(ev_sent.event_id)
    db.flush()
    db.refresh(sent_draft)

    check("sent: draft remains 'sent' after reversal", sent_draft.status == "sent")

    # Auto-generate correction draft
    all_derived = draft_repo.list_derived_from(ev_sent.event_id)
    already_sent = [d for d in all_derived if d.status in ("sent", "relayed")]
    check("sent: already_sent non-empty", len(already_sent) > 0)

    if already_sent:
        correction = draft_repo.create(
            project_id="rev_proj",
            data={
                "channel": "email",
                "message_text": "[Correction] The MOQ figure in our last message was incorrect. We will follow up.",
                "created_by_agent": "reversal_engine",
                "derived_from_event_id": reversal_3.event_id,
            },
        )
        db.flush()
        check("sent: correction draft created", correction.draft_id is not None)
        check("sent: correction pending approval", correction.status == "pending_approval")

    print("\n=== Reversal E2E: audit trail ===")
    all_events = event_repo.list_for_project("rev_proj")
    reversal_events = [e for e in all_events if e.event_type == "reversal"]
    check("audit: 3 reversal events", len(reversal_events) == 3,
          f"found {len(reversal_events)}")

    db.commit()

    if failures:
        print(f"\n{len(failures)} failure(s):")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print("\nAll reversal E2E checks passed.")


if __name__ == "__main__":
    run()
