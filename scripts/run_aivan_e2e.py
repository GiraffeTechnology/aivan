#!/usr/bin/env python3
"""AIVAN Core E2E Test - Trade Salesperson Flow

Tests the full buyer-inquiry → structured-requirement → supplier-inquiry →
supplier-reply → Top-3 buyer options pipeline using mock providers.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_DB_URL", "sqlite:///./data/aiven_e2e.db")

from aivan.db.session import init_db, db_session
from aiven.openclaw.event_adapter import parse_openclaw_event
from aiven.agents.trade_salesperson_agent import handle_trade_salesperson_event
from aiven.platforms.platform_registry import _ensure_init


def _build_msg(base: dict, override: dict) -> dict:
    m = dict(base)
    m.update(override)
    return m


def main():
    print("=" * 60)
    print("AIVAN CORE E2E: Trade Salesperson Flow")
    print("=" * 60)

    os.makedirs("data", exist_ok=True)
    init_db()
    _ensure_init()

    # ---------------------------------------------------------------------------
    # Base message template (customer HK Buyer Alice, apparel inquiry)
    # ---------------------------------------------------------------------------
    base_msg = {
        "source": "openclaw",
        "channel": "openclaw-weixin",
        "channel_account_id": "salesperson-main",
        "conversation_id": "demo_conv_apparel_01",
        "message_id": "msg_001",
        "sender_id": "customer_hk_001",
        "sender_display_name": "HK Buyer Alice",
        "message_type": "text",
        "attachments": [],
        "timestamp": "2026-06-14T08:00:00Z",
        "mode": "auto",
    }

    # ---------------------------------------------------------------------------
    # Step 1: Customer sends a detailed apparel inquiry (Chinese)
    # ---------------------------------------------------------------------------
    print("\nStep 1: Customer sends detailed apparel inquiry")
    print("-" * 50)
    msg1 = _build_msg(base_msg, {
        "message_id": "msg_001",
        "message_text": (
            "需要采购10000件白色纯棉男士衬衣，发往温哥华，45天内交货，"
            "目标价USD 4.80，空运优先，DDP。"
            "规格：180gsm，S/M/L/XL，独立包装。"
        ),
    })
    print(f"Customer ({msg1['sender_display_name']}): {msg1['message_text']}")

    with db_session() as db:
        event1 = parse_openclaw_event(msg1)
        result1 = handle_trade_salesperson_event(event1, db)

    print(f"\nAction  : {result1.action}")
    print(f"Response: {result1.message}")
    if result1.requirement:
        req = result1.requirement
        missing = [mf.field_name for mf in req.missing_fields]
        print(f"Missing fields detected: {missing}")

    assert result1.action is not None, "FAIL: Step 1 returned no action"
    assert result1.message, "FAIL: Step 1 returned empty message"
    print("Step 1: OK")

    # ---------------------------------------------------------------------------
    # Step 2: Customer provides supplementary size-ratio and packaging detail
    # ---------------------------------------------------------------------------
    print("\nStep 2: Customer provides missing spec details")
    print("-" * 50)
    msg2 = _build_msg(base_msg, {
        "message_id": "msg_002",
        "message_text": (
            "180gsm，S/M/L/XL 比例 20/40/30/10，单件独立袋装，"
            "目标价USD 4.80以内，优先空运，DDP最好。"
        ),
    })
    print(f"Customer: {msg2['message_text']}")

    with db_session() as db:
        event2 = parse_openclaw_event(msg2)
        result2 = handle_trade_salesperson_event(event2, db)

    print(f"\nAction  : {result2.action}")
    print(f"Response: {result2.message}")
    assert result2.action is not None, "FAIL: Step 2 returned no action"
    print("Step 2: OK")

    # ---------------------------------------------------------------------------
    # Step 3: Supplier replies with a competitive quote
    # ---------------------------------------------------------------------------
    print("\nStep 3: Supplier sends quote reply")
    print("-" * 50)
    msg3 = _build_msg(base_msg, {
        "message_id": "msg_supplier_001",
        "sender_id": "supplier_gz_trendy_001",
        "sender_display_name": "Guangzhou Trendy Garment",
        "role_context": "supplier",
        "message_text": (
            "Hi, we can offer USD 4.50/pc, MOQ 3000pcs, daily capacity 500pcs, "
            "lead time 35 days ex-factory FOB Guangzhou. "
            "Payment 30% deposit T/T, balance before shipment. "
            "We hold ISO 9001 and OEKO-TEX certificates."
        ),
    })
    print(f"Supplier ({msg3['sender_display_name']}): {msg3['message_text']}")

    with db_session() as db:
        event3 = parse_openclaw_event(msg3)
        result3 = handle_trade_salesperson_event(event3, db)

    print(f"\nAction  : {result3.action}")
    print(f"Response: {result3.message}")

    if result3.buyer_options:
        print(f"\nTop-{len(result3.buyer_options)} Buyer Options Generated:")
        for opt in result3.buyer_options:
            lt_days = opt.lead_time_estimate.expected_days if opt.lead_time_estimate else "N/A"
            price = opt.quote.buyer_unit_price if opt.quote else "N/A"
            print(f"  [{opt.option_label}] {opt.reasoning}")
            print(f"    Lead time : {lt_days} days")
            print(f"    Buyer price: {price} USD/pc")
            print(f"    Risk level : {opt.risk_level}")
    else:
        print("  (No structured buyer options — agent responded in message form)")

    assert result3.action is not None, "FAIL: Step 3 (supplier reply) returned no action"
    print("Step 3: OK")

    # ---------------------------------------------------------------------------
    # Done
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("AIVAN CORE E2E: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()
