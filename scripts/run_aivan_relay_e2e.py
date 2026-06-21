#!/usr/bin/env python3
"""E2E smoke test for the guided-relay flow (Workstream C).

Runs entirely in-process with mock LLM and mock channel adapters.
Exit 0 = all assertions passed.
"""
from __future__ import annotations
import os
import sys

# Mock modes
os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_LINE_ENABLED", "true")
os.environ.setdefault("AIVAN_LINE_MODE", "mock")
os.environ.setdefault("AIVAN_EMAIL_MODE", "mock")
os.environ["AIVAN_DB_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from aivan.db.models import Base
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.inbound_repo import InboundRelayRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
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

    print("\n=== Relay E2E: outbound (4 channels) ===")
    for channel, expected_action in [
        ("email",    "sent"),
        ("line",     "sent"),
        ("wechat",   "awaiting_relay"),
        ("wangwang", "awaiting_relay"),
    ]:
        d = draft_repo.create(
            project_id="e2e_relay",
            data={"channel": channel, "target_peer_id": "peer@example.com",
                  "message_text": f"E2E msg for {channel}", "created_by_agent": "e2e"},
        )
        draft_repo.approve(d.draft_id)
        db.flush()
        result = send_draft(d.draft_id, db)
        check(
            f"{channel}: success", result.success,
            f"error={result.error}",
        )
        check(
            f"{channel}: action={expected_action}",
            result.action == expected_action,
            f"got {result.action}",
        )
        db.refresh(d)
        check(
            f"{channel}: db status",
            d.status in ("sent", "awaiting_relay"),
            f"got {d.status}",
        )

    print("\n=== Relay E2E: confirm relay ===")
    # Create a wechat draft, put it in awaiting_relay, then confirm
    wc = draft_repo.create(
        project_id="e2e_relay",
        data={"channel": "wechat", "target_peer_id": "wx_123",
              "message_text": "Please confirm", "created_by_agent": "e2e"},
    )
    draft_repo.approve(wc.draft_id)
    db.flush()
    send_draft(wc.draft_id, db)
    db.flush()
    relayed = draft_repo.mark_relayed(wc.draft_id, confirmed_by="operator")
    check("relay confirm: status=relayed", relayed.status == "relayed")
    check("relay confirm: confirmed_by set", relayed.relay_confirmed_by == "operator")
    check("relay confirm: not in outbox",
          not any(c.draft_id == wc.draft_id for c in draft_repo.list_awaiting_relay()))

    print("\n=== Relay E2E: inbound paste ===")
    ev = event_repo.append(
        project_id="thread_e2e",
        event_type="inbound_relay_paste",
        summary="Pasted supplier reply",
        payload={"pasted_text": "We can deliver in 7 days."},
    )
    inb = inbound_repo.create(
        thread_id="thread_e2e",
        counterparty_id="supplier_001",
        pasted_text="We can deliver in 7 days.",
        channel="wechat",
        linked_execution_event_id=ev.event_id,
    )
    check("inbound: id created", inb.inbound_id.startswith("inb_"))
    check("inbound: not superseded", not inb.superseded)
    check("inbound: linked event", inb.linked_execution_event_id == ev.event_id)

    all_events = event_repo.list_for_project("thread_e2e")
    check("inbound: event in log", len(all_events) >= 1)

    db.commit()

    if failures:
        print(f"\n{len(failures)} failure(s):")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print(f"\nAll relay E2E checks passed.")


if __name__ == "__main__":
    run()
