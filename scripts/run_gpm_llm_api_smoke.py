#!/usr/bin/env python3
"""
GPM Live Qwen API Smoke Test
For CI and manual verification.
Requires the GPM_LLM_API_KEY environment variable (or QWEN_API_KEY).

Exit codes: 0 = PASS, 1 = FAIL.
"""

import os
import sys
import json
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("gpm-smoke")


def _contains_unavailable_runtime(value) -> bool:
    """Recursively check whether a packet value signals an unavailable LLM runtime.

    Handles nested dicts/lists and JSON-encoded strings (e.g. llm_reasoning
    that contains serialised JSON) so an escaped runtime_status field cannot
    slip past a flat substring scan.
    """
    if isinstance(value, dict):
        if str(value.get("runtime_status", "")).lower() == "unavailable":
            return True
        return any(_contains_unavailable_runtime(v) for v in value.values())

    if isinstance(value, list):
        return any(_contains_unavailable_runtime(v) for v in value)

    if isinstance(value, str):
        lowered = value.lower()
        if "runtime unavailable" in lowered:
            return True
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return "runtime_status" in lowered and "unavailable" in lowered
        return _contains_unavailable_runtime(decoded)

    return False


def check_env() -> str:
    key = os.environ.get("GPM_LLM_API_KEY") or os.environ.get("QWEN_API_KEY", "")
    if not key:
        log.error("FAIL: GPM_LLM_API_KEY / QWEN_API_KEY not set")
        sys.exit(1)
    if key[:5] not in ("sk-ws", "sk-"):
        log.warning("Key format looks unusual — continuing")
    log.info("API key present: %s****", key[:8])
    return key


def test_qwen_connectivity(key: str) -> bool:
    """Call DashScope directly to verify connectivity, bypassing the GPM layer."""
    import urllib.request
    import urllib.error

    base_url = os.environ.get(
        "QWEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    model = os.environ.get("QWEN_MODEL", "qwen-turbo")

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
        "max_tokens": 10,
        "temperature": 0,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read())
            content = body["choices"][0]["message"]["content"]
            log.info("Qwen connectivity OK — response: %r", content)
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log.error("Qwen connectivity FAIL: HTTP %d — %s", e.code, body)
        return False
    except Exception as exc:
        log.error("Qwen connectivity FAIL: %s", exc)
        return False


def test_gpm_llm_runtime(key: str) -> bool:
    """Test through the GPM LLM runtime layer to verify Aivan integration."""
    try:
        from aivan.gpm.llm_runtime import analyze_quote
    except ImportError:
        if os.environ.get("ALLOW_GPM_RUNTIME_SKIP") == "true":
            log.warning("aivan.gpm.llm_runtime not found — skipping because ALLOW_GPM_RUNTIME_SKIP=true")
            return True
        log.error("aivan.gpm.llm_runtime not found — set ALLOW_GPM_RUNTIME_SKIP=true to skip")
        return False

    try:
        result = analyze_quote(
            sku="CI-SMOKE-SKU-001",
            supplier_quote=3.75,
            currency="USD",
            quantity=500,
        )

        # Verify that the runtime has not degraded to unavailable; live Qwen must be online.
        if result.get("runtime_status") == "unavailable":
            reason = result.get("reason", "unknown")
            log.error(
                "GPM runtime FAIL: LLM unavailable (reason=%s) — "
                "live Qwen must be reachable for this test to pass",
                reason,
            )
            return False

        # Verify human_approval_required = True.
        if result.get("human_approval_required") is not True:
            log.error("GPM runtime FAIL: human_approval_required != True")
            return False

        # Verify that quote_position is valid.
        valid_positions = {
            "below_market", "within_low_range", "within_mid_range",
            "within_high_range", "above_market", "insufficient_data",
        }
        if result.get("quote_position") not in valid_positions:
            log.error("GPM runtime FAIL: invalid quote_position %r", result.get("quote_position"))
            return False

        # Verify that recommendation is valid.
        valid_recs = {"accept", "negotiate", "reject", "request_more_info", "human_review_required"}
        if result.get("recommendation") not in valid_recs:
            log.error("GPM runtime FAIL: invalid recommendation %r", result.get("recommendation"))
            return False

        # Verify that confidence is valid.
        if result.get("confidence") not in {"high", "medium", "low"}:
            log.error("GPM runtime FAIL: invalid confidence %r", result.get("confidence"))
            return False

        # Verify that the key does not appear in the output.
        result_str = json.dumps(result)
        if key[:20] in result_str:
            log.error("SECURITY FAIL: API key fragment in GPM runtime output!")
            return False

        log.info(
            "GPM runtime OK — position=%s recommendation=%s confidence=%s",
            result.get("quote_position"),
            result.get("recommendation"),
            result.get("confidence"),
        )
        return True

    except Exception as exc:
        log.error("GPM runtime FAIL: %s", exc)
        return False


def test_gpm_api_service(key: str) -> bool:
    """
    Start the GPM API service and send a real quote-guidance request using live Qwen.
    Verify the packet structure, dispatched=False, and absence of key leakage.
    """
    import subprocess
    import urllib.request
    import urllib.error

    # Project root: the parent directory of scripts/.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_dir = os.path.join(project_root, "src")

    env = {
        **os.environ,
        # actual provider variables consumed by the service
        "AIVAN_LLM_PROVIDER": "qwen",
        "QWEN_API_KEY": key,
        "QWEN_MODEL": os.environ.get("QWEN_MODEL", "qwen-turbo"),
        "QWEN_BASE_URL": os.environ.get(
            "QWEN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        # GPM-layer variables
        "GPM_CONTEXT_RETRIEVER": "mock",
        "GPM_LLM_RUNTIME_MODE": "llm_api",
        "GPM_ENABLE_LLM_API": "true",
        "GPM_LLM_PROVIDER": "qwen",
        "GPM_LLM_API_MODEL": os.environ.get("QWEN_MODEL", "qwen-turbo"),
        "GPM_LLM_API_KEY": key,
        "GIRAFFE_DB_BASE_URL": "",
        "AIVAN_TENANT_ID": "ci-smoke",
        # Ensure the subprocess can find the aivan package in the src/ layout.
        "PYTHONPATH": src_dir + (
            os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""
        ),
    }

    # Use the current virtual environment Python instead of uv run to avoid rebuilding the environment.
    python_exe = sys.executable

    # Start the service.
    proc = subprocess.Popen(
        [python_exe, "-m", "aivan.gpm.server"],
        env=env,
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(5)

    if proc.poll() is not None:
        out, _ = proc.communicate()
        log.error("GPM service failed to start:\n%s", out.decode())
        return False

    try:
        # healthz
        req = urllib.request.Request("http://localhost:8080/api/gpm/healthz")
        with urllib.request.urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read())
            log.info("healthz: %s", health)
            assert health.get("status") == "ok", f"healthz not ok: {health}"

        # quote-guidance（live Qwen）
        payload = json.dumps({
            "case_id": "case-ci-smoke-001",
            "quote_id": "quote-ci-smoke-001",
            "sku": "CI-SMOKE-E2E-001",
            "supplier_id": "SUP-CI-01",
            "supplier_quote": 3.75,
            "currency": "USD",
            "quantity": 500,
            "buyer_unit_price": 4.5,
            "buyer_total": 2250.0,
            "supplier_total": 1875.0,
            "margin_rate": 0.1667,
            "gltg_run_id": "gltg-ci-smoke-001",
            "gltg_api_version": "v2",
            "enable_llm_analysis": True,
        }).encode()

        req = urllib.request.Request(
            "http://localhost:8080/api/gpm/quote-guidance",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            packet = json.loads(resp.read())

        # Verify dispatched = False, a core constraint.
        assert packet.get("dispatched") is False, \
            f"APPROVAL BOUNDARY FAIL: dispatched={packet.get('dispatched')}"

        # Verify human_approval_required = True.
        assert packet.get("human_approval_required") is True, \
            "human_approval_required must be True"

        # Verify that the key has not leaked.
        packet_str = json.dumps(packet)
        assert key[:20] not in packet_str, \
            "SECURITY FAIL: API key in packet response"

        # Verify that the runtime has not degraded to unavailable, including JSON nested in llm_reasoning.
        assert not _contains_unavailable_runtime(packet), \
            "LLM runtime unavailable; this is not a valid live Qwen E2E pass"

        # Verify that actual LLM analysis fields exist and have valid values.
        valid_positions = {
            "below_market",
            "within_low_range",
            "within_mid_range",
            "within_high_range",
            "above_market",
            "insufficient_data",
        }
        valid_recommendations = {
            "accept",
            "negotiate",
            "reject",
            "request_more_info",
            "human_review_required",
        }
        valid_confidences = {"high", "medium", "low"}

        assert packet.get("quote_position") in valid_positions, \
            f"Missing or invalid quote_position: {packet.get('quote_position')!r}"
        assert packet.get("recommendation") in valid_recommendations, \
            f"Missing or invalid recommendation: {packet.get('recommendation')!r}"
        assert packet.get("confidence") in valid_confidences, \
            f"Missing or invalid confidence: {packet.get('confidence')!r}"

        log.info(
            "GPM E2E OK — packet_id=%s dispatched=%s position=%s recommendation=%s confidence=%s",
            packet.get("packet_id"),
            packet.get("dispatched"),
            packet.get("quote_position"),
            packet.get("recommendation"),
            packet.get("confidence"),
        )
        return True

    except AssertionError as exc:
        log.error("GPM E2E FAIL: %s", exc)
        return False
    except Exception as exc:
        log.error("GPM E2E FAIL: %s", exc)
        return False
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def main():
    log.info("=" * 60)
    log.info("GPM Live Qwen Smoke Test")
    log.info("=" * 60)

    key = check_env()
    results = {}

    # Test 1: Qwen connectivity.
    log.info("\n── Test 1: Qwen API connectivity ──")
    results["qwen_connectivity"] = test_qwen_connectivity(key)

    # Test 2: GPM LLM runtime layer.
    log.info("\n── Test 2: GPM LLM runtime layer ──")
    results["gpm_llm_runtime"] = test_gpm_llm_runtime(key)

    # Test 3: GPM API service E2E
    log.info("\n── Test 3: GPM API service E2E ──")
    results["gpm_api_e2e"] = test_gpm_api_service(key)

    # Summary.
    log.info("\n" + "=" * 60)
    log.info("SMOKE RESULTS:")
    all_pass = True
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        log.info("  %-30s %s", name, status)
        if not ok:
            all_pass = False

    log.info("=" * 60)
    if all_pass:
        log.info("ALL SMOKE TESTS PASSED")
        sys.exit(0)
    else:
        log.error("SMOKE TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
