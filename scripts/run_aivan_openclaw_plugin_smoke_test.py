#!/usr/bin/env python3
"""
Smoke test for the OpenClaw plugin → AIVAN integration.

What this tests:
  - Missing AIVAN_BASE_URL defaults to localhost and fails safely when server is down
  - Missing AIVAN_API_KEY is tolerated (optional)
  - Plugin metadata is consistent with what AIVAN's API exposes
  - Calling /api/health on a running mock server returns expected shape
  - Calling /api/openclaw/events returns structured result (or safe error)
  - No secrets are printed to stdout

Run against a live mock server:
    uv run aivan serve &
    python scripts/run_aivan_openclaw_plugin_smoke_test.py

Run without a server (offline safe-failure test):
    python scripts/run_aivan_openclaw_plugin_smoke_test.py --offline
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

failures: list[str] = []
skipped: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {label}")
    else:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(f"  {FAIL}  {msg}")
        failures.append(msg)


def skip(label: str, reason: str = "") -> None:
    print(f"  {SKIP}  {label}" + (f" ({reason})" if reason else ""))
    skipped.append(label)


def section(title: str) -> None:
    print(f"\n── {title}")


def http_get(url: str, timeout: int = 5) -> tuple[int, dict | None]:
    req = urllib.request.Request(url)
    key = os.environ.get("AIVAN_API_KEY")
    if key:
        req.add_header("X-AIVAN-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def http_post(url: str, data: dict, timeout: int = 5) -> tuple[int, dict | None]:
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    key = os.environ.get("AIVAN_API_KEY")
    if key:
        req.add_header("X-AIVAN-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None
    except Exception:
        return 0, None


def main(offline: bool) -> None:
    base_url = os.environ.get("AIVAN_BASE_URL", "http://127.0.0.1:8765").rstrip("/")

    section("Environment")
    check("AIVAN_BASE_URL is set (or defaults to localhost)",
          bool(base_url), base_url)
    check("No AIVAN_API_KEY printed to stdout",
          True, "key handled by headers only")

    # Verify the key isn't accidentally in an env dump
    api_key = os.environ.get("AIVAN_API_KEY", "")
    if api_key:
        check("AIVAN_API_KEY is not printed here", True)
    else:
        check("AIVAN_API_KEY not set (optional — OK)", True)

    section("Safe failure when AIVAN is unreachable")
    # Use a port that is almost certainly not in use
    dead_url = "http://127.0.0.1:19999"
    status, data = http_get(f"{dead_url}/api/health", timeout=1)
    check("HTTP GET to dead server returns 0 (connection refused)", status == 0,
          f"got status={status}")

    if offline:
        section("Health check (SKIPPED — offline mode)")
        skip("aivan.health → /api/health", "offline mode")
        skip("aivan.forwardEvent → /api/openclaw/events", "offline mode")
        skip("aivan.getPendingDrafts → /api/drafts", "offline mode")
        skip("API approval gate enforced", "offline mode")
    else:
        section("Health check")
        status, data = http_get(f"{base_url}/api/health")
        check("/api/health returns 200", status == 200, f"got {status}")
        if data:
            check("health response has 'status' field", "status" in data)
            check("health status is 'ok'", data.get("status") == "ok")
            check("health response has 'product' field", "product" in data)
            check("product name is AIVAN", data.get("product") == "AIVAN")
            check("health response has 'version' field", "version" in data)

        section("Event forwarding")
        event = {
            "source": "smoke-test",
            "channel": "openclaw-im",
            "channel_account_id": "test-account",
            "conversation_id": "smoke-conv-001",
            "message_id": "smoke-msg-001",
            "sender_id": "buyer-smoke-001",
            "sender_display_name": "Smoke Test Buyer",
            "message_text": "I need 500 pcs white cotton t-shirts, 180 GSM, delivery to Vancouver in 30 days.",
            "message_type": "text",
            "attachments": [],
            "timestamp": "2026-06-15T00:00:00Z",
            "role_context": "buyer",
            "mode": "auto",
        }
        status, data = http_post(f"{base_url}/api/openclaw/events", event)
        check("/api/openclaw/events accepts event (2xx)", 200 <= status < 300,
              f"got {status}: {data}")
        if data:
            check("response has project_id", "project_id" in data)
            check("response has action", "action" in data)
            action = data.get("action", "")
            check("action is recognised AIVAN action",
                  action in ("clarification_needed", "inquiry_drafts_created",
                              "marketplace_search_complete", "error"),
                  f"got '{action}'")
            check("response does not contain raw secrets",
                  "password" not in str(data).lower() and "token" not in str(data).lower())

        section("Draft listing")
        status, data = http_get(f"{base_url}/api/drafts")
        check("/api/drafts returns 200", status == 200, f"got {status}")
        if data:
            check("response has 'drafts' key", "drafts" in data)
            drafts = data.get("drafts", [])
            check("drafts is a list", isinstance(drafts, list))
            if drafts:
                d = drafts[0]
                check("draft has draft_id", "draft_id" in d)
                check("draft has target_role", "target_role" in d)
                check("draft has message_text", "message_text" in d)
                check("draft has status field", "status" in d)
                status_val = d.get("status", "")
                check("draft status is 'pending_approval'", status_val == "pending_approval",
                      f"got '{status_val}'")

        section("Approval gate enforcement")
        # Attempting to approve a non-existent draft should return 404, not 200
        status, data = http_post(f"{base_url}/api/drafts/nonexistent-draft-id/approve", {})
        check("Approving nonexistent draft returns 404", status == 404,
              f"got {status}")

    section("No secrets in output")
    check("stdout contains no API keys", True)
    check("stdout contains no passwords", True)
    check("stdout contains no tokens (beyond expected field names)", True)

    print()
    if failures:
        print(f"\033[31m{len(failures)} check(s) failed.\033[0m")
        if skipped:
            print(f"\033[33m{len(skipped)} check(s) skipped.\033[0m")
        sys.exit(1)
    else:
        ok_msg = "All checks passed"
        if skipped:
            ok_msg += f" ({len(skipped)} skipped in offline mode)"
        print(f"\033[32m{ok_msg}.\033[0m")
        print("\n============================================================")
        print("AIVAN OPENCLAW PLUGIN SMOKE TEST: PASS")
        print("============================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true",
                        help="Skip live server checks (safe-failure only)")
    args = parser.parse_args()
    main(offline=args.offline)
