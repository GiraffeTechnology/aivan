#!/usr/bin/env python3
"""
GPM Live Qwen API Smoke Test
用于 CI 和手动验证。
需要环境变量：GPM_LLM_API_KEY（或 QWEN_API_KEY）

退出码：0 = PASS，1 = FAIL
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
    """直接调 DashScope 验证连通性（不走 GPM 层）。"""
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
    """通过 GPM LLM runtime 层测试（验证 aiven 集成）。"""
    try:
        from aivan.gpm.runtime import GPMLLMRuntime  # 按实际路径调整
    except ImportError:
        try:
            from aivan.gpm.operator_llm_api_runtime import OperatorLLMApiRuntime as GPMLLMRuntime
        except ImportError:
            if os.environ.get("ALLOW_GPM_RUNTIME_SKIP") == "true":
                log.warning("GPM LLM runtime class not found — skipping because ALLOW_GPM_RUNTIME_SKIP=true")
                return True
            log.error("GPM LLM runtime class not found — set ALLOW_GPM_RUNTIME_SKIP=true to skip")
            return False

    try:
        runtime = GPMLLMRuntime()
        result = runtime.generate_json({
            "sku": "CI-SMOKE-SKU-001",
            "supplier_quote": 3.75,
            "context": "CI smoke test — 20 evidence samples, P50=3.58, P75=3.79",
            "prompt": (
                "Analyze this supplier quote for procurement decision. "
                "Return JSON with human_approval_required, recommendation, "
                "quote_position, confidence, reasoning."
            ),
        })

        # 验证必填字段
        required = {"human_approval_required", "recommendation", "quote_position", "confidence"}
        missing = required - result.keys()
        if missing:
            log.error("GPM runtime FAIL: missing keys %s", missing)
            return False

        # 验证 human_approval_required = True
        if result.get("human_approval_required") is not True:
            log.error("GPM runtime FAIL: human_approval_required != True")
            return False

        # 验证 recommendation 值合法
        valid_recs = {"accept", "negotiate", "reject", "request_more_info", "human_review_required"}
        rec = result.get("recommendation", "")
        if rec not in valid_recs:
            log.error("GPM runtime FAIL: invalid recommendation %r", rec)
            return False

        # 验证 key 未出现在输出中
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
    启动 GPM API service，发送真实 quote-guidance 请求（live Qwen）。
    验证 packet 结构、dispatched=False、key 不泄露。
    """
    import subprocess
    import urllib.request
    import urllib.error

    # 项目根目录（scripts/ 的上一级）
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
        # 确保子进程能找到 aivan 包（src/ layout）
        "PYTHONPATH": src_dir + (
            os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""
        ),
    }

    # 使用当前 venv 的 Python 而非再次调用 uv run（避免 venv 重建）
    python_exe = sys.executable

    # 启动 service
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
            "sku": "CI-SMOKE-E2E-001",
            "supplier_id": "SUP-CI-01",
            "supplier_quote": 3.75,
            "currency": "USD",
            "quantity": 500,
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

        # 验证 dispatched = False（核心约束）
        assert packet.get("dispatched") is False, \
            f"APPROVAL BOUNDARY FAIL: dispatched={packet.get('dispatched')}"

        # 验证 human_approval_required = True
        assert packet.get("human_approval_required") is True, \
            "human_approval_required must be True"

        # 验证 key 未泄露
        packet_str = json.dumps(packet)
        assert key[:20] not in packet_str, \
            "SECURITY FAIL: API key in packet response"

        # 验证 runtime 未降级为 unavailable
        packet_str_lower = packet_str.lower()
        assert '"runtime_status": "unavailable"' not in packet_str_lower, \
            "LLM runtime unavailable; this is not a valid live Qwen E2E pass"
        assert "runtime unavailable" not in packet_str_lower, \
            "LLM runtime unavailable; this is not a valid live Qwen E2E pass"

        # 验证真实 LLM 分析字段存在且值合法
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

    # Test 1: Qwen 连通性
    log.info("\n── Test 1: Qwen API connectivity ──")
    results["qwen_connectivity"] = test_qwen_connectivity(key)

    # Test 2: GPM LLM runtime 层
    log.info("\n── Test 2: GPM LLM runtime layer ──")
    results["gpm_llm_runtime"] = test_gpm_llm_runtime(key)

    # Test 3: GPM API service E2E
    log.info("\n── Test 3: GPM API service E2E ──")
    results["gpm_api_e2e"] = test_gpm_api_service(key)

    # 汇总
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
