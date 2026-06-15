from __future__ import annotations
import os
import sys
import argparse

def cmd_init(args):
    print("Initializing AIVAN...")
    os.makedirs("data", exist_ok=True)
    from aivan.db.session import init_db
    init_db()
    from aivan.platforms.platform_registry import _ensure_init
    _ensure_init()
    print("Database initialized.")
    print("Platform whitelist initialized (Alibaba, AliExpress built-in).")
    print("AIVAN ready. Run: uv run aivan serve")

def cmd_serve(args):
    import uvicorn
    host = os.environ.get("AIVAN_HOST", "127.0.0.1")
    port = int(os.environ.get("AIVAN_PORT", "8765"))
    print(f"Starting AIVAN on http://{host}:{port}/app")
    uvicorn.run("aivan.api.main:app", host=host, port=port, reload=False)

def cmd_import_suppliers(args):
    path = args.file
    if not path or not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)
    from aivan.sourcing.supplier_importer import import_from_csv_file
    from aivan.db.session import db_session
    with db_session() as db:
        count, errors = import_from_csv_file(path, db)
    print(f"Imported {count} suppliers.")
    if errors:
        print(f"Errors: {errors}")

def cmd_demo(args):
    print("=" * 60)
    print("AIVAN TRADE SALESPERSON DEMO")
    print("=" * 60)
    from aivan.db.session import db_session, init_db
    init_db()
    from aivan.openclaw.contracts import OpenClawEvent
    from aivan.openclaw.event_adapter import parse_openclaw_event
    from aivan.agents.trade_salesperson_agent import handle_trade_salesperson_event
    from aivan.platforms.platform_registry import _ensure_init
    _ensure_init()

    msg1 = {
        "source": "openclaw", "channel": "openclaw-weixin", "channel_account_id": "salesperson-main",
        "conversation_id": "demo_conv_001", "message_id": "demo_msg_001",
        "sender_id": "customer_001", "sender_display_name": "Demo Customer",
        "message_text": "我需要采购10000件白色纯棉男士衬衣，发到温哥华，45天内交货。",
        "message_type": "text", "attachments": [], "timestamp": "", "mode": "auto",
    }
    print("\nStep 1: Customer inquiry received")
    print(f"Message: {msg1['message_text']}")
    with db_session() as db:
        event = parse_openclaw_event(msg1)
        result1 = handle_trade_salesperson_event(event, db)
    print(f"Action: {result1.action}")
    print(f"Message: {result1.message}")
    if result1.requirement:
        req = result1.requirement
        print(f"Missing fields: {[mf.field_name for mf in req.missing_fields]}")

    msg2 = dict(msg1)
    msg2["message_id"] = "demo_msg_002"
    msg2["message_text"] = "180gsm，S/M/L/XL = 20/40/30/10，单件独立袋装，目标价USD 4.80以内，优先空运，DDP最好。"
    print("\nStep 2: Customer provides missing details")
    print(f"Message: {msg2['message_text']}")
    with db_session() as db:
        event2 = parse_openclaw_event(msg2)
        result2 = handle_trade_salesperson_event(event2, db)
    print(f"Action: {result2.action}")
    print(f"Message: {result2.message}")

    print("\nStep 3: Simulating supplier reply...")
    supplier_reply = dict(msg1)
    supplier_reply["message_id"] = "demo_msg_003"
    supplier_reply["sender_id"] = "supplier_001"
    supplier_reply["sender_display_name"] = "Guangzhou Trendy Garment"
    supplier_reply["role_context"] = "supplier"
    supplier_reply["message_text"] = "Hello, we can offer USD 4.50/pc, MOQ 3000pcs, daily capacity 500pcs, lead time 35 days, FOB Guangzhou, 30% deposit."
    with db_session() as db:
        event3 = parse_openclaw_event(supplier_reply)
        result3 = handle_trade_salesperson_event(event3, db)
    print(f"Action: {result3.action}")
    print(f"Message: {result3.message}")
    if result3.buyer_options:
        print("\nTop-3 Buyer Options:")
        for opt in result3.buyer_options:
            lt_days = opt.lead_time_estimate.expected_days if opt.lead_time_estimate else "N/A"
            price = opt.quote.buyer_unit_price if opt.quote else "N/A"
            print(f"  {opt.option_label}: {opt.reasoning}")
            print(f"    Lead time: {lt_days} days | Buyer price: {price} USD | Risk: {opt.risk_level}")

    print("\n" + "=" * 60)
    print("AIVAN TRADE SALESPERSON E2E: PASS")
    print("=" * 60)

def cmd_demo_marketplace(args):
    print("=" * 60)
    print("AIVAN MARKETPLACE SOURCING DEMO")
    print("=" * 60)
    from aivan.db.session import init_db, db_session
    init_db()
    from aivan.platforms.platform_registry import _ensure_init
    _ensure_init()
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.sourcing.marketplaces.search_query_builder import build_marketplace_queries
    from aivan.sourcing.marketplaces.alibaba_connector import search_alibaba
    from aivan.risk.supplier_risk_agent import run_risk_screening

    req = BuyerRequirement(
        project_id="demo_marketplace_001",
        category="apparel", product_type="men's shirt",
        quantity=10000, fabric_material="100% cotton", gsm=180,
        color="white", size_ratio="S/M/L/XL=20/40/30/10",
        destination="Vancouver", delivery_days=45, target_unit_price=4.80,
        incoterms="DDP", logistics_preference="air",
    )
    queries = build_marketplace_queries(req)
    print(f"\nGenerated {len(queries)} search queries:")
    for q in queries:
        print(f"  - {q}")

    print("\nSearching Alibaba (mock mode)...")
    results = search_alibaba(queries[0])
    print(f"Found {len(results.candidates)} candidates:")
    for c in results.candidates:
        print(f"  - {c.supplier_name} | MOQ: {c.moq} | Price: {c.price_min}-{c.price_max} USD | Risk flags: {c.risk_flags}")

    print("\nRunning risk screening on top 2 candidates...")
    for cand in results.candidates[:2]:
        report = run_risk_screening(cand.supplier_name, candidate_id=cand.candidate_id, existing_flags=cand.risk_flags)
        print(f"  {cand.supplier_name}: {report.risk_score.risk_level.upper()} risk | Action: {report.risk_score.recommended_action}")

    print("\n" + "=" * 60)
    print("AIVAN MARKETPLACE SOURCING E2E: PASS")
    print("=" * 60)

def cmd_demo_risk_check(args):
    print("=" * 60)
    print("AIVAN RISK CHECK DEMO")
    print("=" * 60)
    from aivan.risk.supplier_risk_agent import run_risk_screening
    from aivan.risk.risk_report import format_risk_report_text

    supplier_name = getattr(args, "supplier_name", None) or "Example Supplier Co Ltd"
    print(f"\nRunning risk check for: {supplier_name}")
    report = run_risk_screening(supplier_name, category="apparel")
    print(format_risk_report_text(report))
    print("\n" + "=" * 60)

def cmd_risk_check(args):
    from aivan.risk.supplier_risk_agent import run_risk_screening
    from aivan.risk.risk_report import format_risk_report_text
    supplier_name = args.supplier_name or "Unknown Supplier"
    report = run_risk_screening(supplier_name, category="")
    print(format_risk_report_text(report))

def cmd_platforms(args):
    sub = args.sub_command
    if sub == "list":
        from aivan.platforms.platform_registry import list_all_platforms, _ensure_init
        _ensure_init()
        for p in list_all_platforms():
            print(f"  [{p.status}] {p.platform_id}: {p.display_name} | Domains: {p.domain_patterns}")
    elif sub == "whitelist":
        from aivan.platforms.platform_registry import list_trusted_platforms, _ensure_init
        _ensure_init()
        for p in list_trusted_platforms():
            print(f"  {p.platform_id}: {p.display_name}")
    elif sub == "suggest":
        from aivan.platforms.platform_registry import suggest_platform, _ensure_init
        _ensure_init()
        sug = suggest_platform(args.domain, args.reason or "User suggestion")
        print(f"Suggestion created: {sug.suggestion_id}")
    else:
        print(f"Unknown sub-command: {sub}")

def cmd_accounts(args):
    sub = args.sub_command
    from aivan.db.session import init_db, db_session
    init_db()
    if sub == "list":
        from aivan.openclaw.account_delegation import list_accounts
        with db_session() as db:
            accounts = list_accounts(db)
        if not accounts:
            print("No accounts registered.")
        for a in accounts:
            print(f"  [{a.status}] {a.account_connection_id}: {a.platform} | {a.display_name}")
    elif sub == "register":
        import json
        path = getattr(args, "file", None)
        if not path:
            print("--file required")
            sys.exit(1)
        with open(path) as f:
            data = json.load(f)
        from aivan.openclaw.account_delegation import register_account
        with db_session() as db:
            account = register_account(db, data)
        print(f"Registered: {account.account_connection_id}")
    elif sub == "revoke":
        account_id = getattr(args, "account_id", None)
        if not account_id:
            print("Account ID required")
            sys.exit(1)
        from aivan.openclaw.account_delegation import revoke_account
        with db_session() as db:
            revoke_account(db, account_id)
        print(f"Revoked: {account_id}")

def cmd_test(args):
    import subprocess
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"], cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    sys.exit(result.returncode)

def main():
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(prog="aivan", description="AIVAN - AI Trade Salesperson CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize AIVAN database and settings")
    serve_p = subparsers.add_parser("serve", help="Start AIVAN local web server")
    subparsers.add_parser("demo", help="Run core AIVAN E2E demo")
    subparsers.add_parser("demo-marketplace", help="Run marketplace sourcing demo")
    subparsers.add_parser("demo-risk-check", help="Run risk check demo")
    subparsers.add_parser("test", help="Run test suite")

    import_p = subparsers.add_parser("import-suppliers", help="Import suppliers from CSV")
    import_p.add_argument("file", nargs="?", default="data/sample_suppliers.csv")

    import_mp = subparsers.add_parser("import-marketplace-results", help="Import marketplace results from CSV")
    import_mp.add_argument("file", nargs="?", default="data/sample_marketplace_suppliers.csv")

    risk_p = subparsers.add_parser("risk-check", help="Run risk check for a supplier")
    risk_p.add_argument("--supplier-name", default="Unknown Supplier")

    platforms_p = subparsers.add_parser("platforms", help="Platform whitelist management")
    platform_sub = platforms_p.add_subparsers(dest="sub_command")
    platform_sub.add_parser("list")
    platform_sub.add_parser("whitelist")
    sug_p = platform_sub.add_parser("suggest")
    sug_p.add_argument("--domain", required=True)
    sug_p.add_argument("--reason", default="")

    accounts_p = subparsers.add_parser("accounts", help="Account management")
    acc_sub = accounts_p.add_subparsers(dest="sub_command")
    acc_sub.add_parser("list")
    reg_p = acc_sub.add_parser("register")
    reg_p.add_argument("--file", required=True)
    rev_p = acc_sub.add_parser("revoke")
    rev_p.add_argument("account_id")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "serve": cmd_serve,
        "demo": cmd_demo,
        "demo-marketplace": cmd_demo_marketplace,
        "demo-risk-check": cmd_demo_risk_check,
        "test": cmd_test,
        "import-suppliers": cmd_import_suppliers,
        "import-marketplace-results": cmd_import_suppliers,
        "risk-check": cmd_risk_check,
        "platforms": cmd_platforms,
        "accounts": cmd_accounts,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
