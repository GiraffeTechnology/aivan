"""
Regression tests for scripts/run_gpm_llm_api_smoke.py validation logic.

Covers the 4 required cases from the PR review:
1. Child process env includes AIVAN_LLM_PROVIDER and QWEN_API_KEY
2. E2E validator fails when packet lacks quote_position/recommendation/confidence
3. E2E validator fails when packet contains runtime_status=unavailable
4. E2E validator passes only when all required fields are present and valid
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import unittest.mock as mock
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the smoke script as a module without executing main()
# ---------------------------------------------------------------------------
_SCRIPT = Path(__file__).parents[3] / "scripts" / "run_gpm_llm_api_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("run_gpm_llm_api_smoke", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


smoke = _load_smoke_module()

_FAKE_KEY = "sk-ws-TESTKEY1234567890abcdef"

# ---------------------------------------------------------------------------
# Helpers that replicate the packet assertion logic inline so we can test it
# without spawning a real subprocess or server.
# ---------------------------------------------------------------------------


def _assert_packet(packet: dict, key: str) -> None:
    """Run the same assertions as test_gpm_api_service() against a packet."""
    packet_str = json.dumps(packet)

    assert packet.get("dispatched") is False, \
        f"APPROVAL BOUNDARY FAIL: dispatched={packet.get('dispatched')}"
    assert packet.get("human_approval_required") is True, \
        "human_approval_required must be True"
    assert key[:20] not in packet_str, \
        "SECURITY FAIL: API key in packet response"

    packet_str_lower = packet_str.lower()
    assert '"runtime_status": "unavailable"' not in packet_str_lower, \
        "LLM runtime unavailable; this is not a valid live Qwen E2E pass"
    assert "runtime unavailable" not in packet_str_lower, \
        "LLM runtime unavailable; this is not a valid live Qwen E2E pass"

    valid_positions = {
        "below_market", "within_low_range", "within_mid_range",
        "within_high_range", "above_market", "insufficient_data",
    }
    valid_recommendations = {
        "accept", "negotiate", "reject",
        "request_more_info", "human_review_required",
    }
    valid_confidences = {"high", "medium", "low"}

    assert packet.get("quote_position") in valid_positions, \
        f"Missing or invalid quote_position: {packet.get('quote_position')!r}"
    assert packet.get("recommendation") in valid_recommendations, \
        f"Missing or invalid recommendation: {packet.get('recommendation')!r}"
    assert packet.get("confidence") in valid_confidences, \
        f"Missing or invalid confidence: {packet.get('confidence')!r}"


# ---------------------------------------------------------------------------
# Case 1 — subprocess env contains AIVAN_LLM_PROVIDER and QWEN_API_KEY
# ---------------------------------------------------------------------------


def test_child_env_contains_provider_vars(monkeypatch, tmp_path):
    """The env dict built in test_gpm_api_service() must include the actual
    provider variables consumed by the service, not only GPM_LLM_API_KEY."""
    captured_env: dict = {}

    def fake_popen(cmd, env, cwd, stdout, stderr):
        captured_env.update(env)
        # Return a mock process that never starts (poll returns non-zero)
        p = mock.MagicMock()
        p.poll.return_value = 1
        p.communicate.return_value = (b"fake startup failure", None)
        return p

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("time.sleep", lambda _: None)

    smoke.test_gpm_api_service(_FAKE_KEY)  # result doesn't matter here

    assert "AIVAN_LLM_PROVIDER" in captured_env, \
        "AIVAN_LLM_PROVIDER missing from subprocess env"
    assert captured_env["AIVAN_LLM_PROVIDER"] == "qwen"

    assert "QWEN_API_KEY" in captured_env, \
        "QWEN_API_KEY missing from subprocess env"
    assert captured_env["QWEN_API_KEY"] == _FAKE_KEY


# ---------------------------------------------------------------------------
# Case 2 — validator fails when LLM analysis fields are absent
# ---------------------------------------------------------------------------


def test_e2e_fails_when_analysis_fields_missing():
    """A packet with dispatched=False and human_approval_required=True but
    no quote_position/recommendation/confidence must fail validation."""
    minimal_packet = {
        "dispatched": False,
        "human_approval_required": True,
        "packet_id": "gpm_pkt_test001",
    }
    with pytest.raises(AssertionError, match="quote_position"):
        _assert_packet(minimal_packet, _FAKE_KEY)


def test_e2e_fails_when_recommendation_missing():
    packet = {
        "dispatched": False,
        "human_approval_required": True,
        "quote_position": "within_low_range",
    }
    with pytest.raises(AssertionError, match="recommendation"):
        _assert_packet(packet, _FAKE_KEY)


def test_e2e_fails_when_confidence_missing():
    packet = {
        "dispatched": False,
        "human_approval_required": True,
        "quote_position": "within_low_range",
        "recommendation": "negotiate",
    }
    with pytest.raises(AssertionError, match="confidence"):
        _assert_packet(packet, _FAKE_KEY)


# ---------------------------------------------------------------------------
# Case 3 — validator fails when runtime_status is unavailable
# ---------------------------------------------------------------------------


def test_e2e_fails_when_runtime_status_unavailable():
    """Packets with runtime_status=unavailable must always fail — even if
    dispatched=False and human_approval_required=True."""
    packet = {
        "dispatched": False,
        "human_approval_required": True,
        "runtime_status": "unavailable",
        "quote_position": "within_low_range",
        "recommendation": "negotiate",
        "confidence": "medium",
    }
    with pytest.raises(AssertionError, match="LLM runtime unavailable"):
        _assert_packet(packet, _FAKE_KEY)


def test_e2e_fails_when_runtime_unavailable_text_in_body():
    """'runtime unavailable' as a string anywhere in the packet also fails."""
    packet = {
        "dispatched": False,
        "human_approval_required": True,
        "error": "runtime unavailable — falling back",
        "quote_position": "within_low_range",
        "recommendation": "negotiate",
        "confidence": "medium",
    }
    with pytest.raises(AssertionError, match="LLM runtime unavailable"):
        _assert_packet(packet, _FAKE_KEY)


# ---------------------------------------------------------------------------
# Case 4 — validator passes only when all required fields are valid
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("position", [
    "below_market", "within_low_range", "within_mid_range",
    "within_high_range", "above_market", "insufficient_data",
])
@pytest.mark.parametrize("recommendation", [
    "accept", "negotiate", "reject", "request_more_info", "human_review_required",
])
@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_e2e_passes_with_valid_full_packet(position, recommendation, confidence):
    packet = {
        "dispatched": False,
        "human_approval_required": True,
        "packet_id": "gpm_pkt_test_valid",
        "quote_position": position,
        "recommendation": recommendation,
        "confidence": confidence,
    }
    _assert_packet(packet, _FAKE_KEY)  # must not raise


def test_e2e_fails_when_dispatched_true():
    packet = {
        "dispatched": True,
        "human_approval_required": True,
        "quote_position": "within_low_range",
        "recommendation": "negotiate",
        "confidence": "medium",
    }
    with pytest.raises(AssertionError, match="APPROVAL BOUNDARY FAIL"):
        _assert_packet(packet, _FAKE_KEY)


def test_e2e_fails_when_api_key_in_packet():
    key = "sk-ws-SECRETKEY1234567890xyz"
    packet = {
        "dispatched": False,
        "human_approval_required": True,
        "quote_position": "within_low_range",
        "recommendation": "negotiate",
        "confidence": "medium",
        "debug_info": key,  # key leaks
    }
    with pytest.raises(AssertionError, match="SECURITY FAIL"):
        _assert_packet(packet, key)


# ---------------------------------------------------------------------------
# Issue 3 — runtime import failure behaviour
# ---------------------------------------------------------------------------


def test_gpm_runtime_fails_without_allow_skip(monkeypatch):
    """When the runtime class cannot be imported and ALLOW_GPM_RUNTIME_SKIP
    is not set, test_gpm_llm_runtime() must return False."""
    monkeypatch.delenv("ALLOW_GPM_RUNTIME_SKIP", raising=False)

    with mock.patch.dict("sys.modules", {
        "aivan.gpm.runtime": None,
        "aivan.gpm.operator_llm_api_runtime": None,
    }):
        # Force both imports to raise ImportError
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _fake_import(name, *args, **kwargs):
            if name in ("aivan.gpm.runtime", "aivan.gpm.operator_llm_api_runtime"):
                raise ImportError(f"fake: {name}")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=_fake_import):
            result = smoke.test_gpm_llm_runtime(_FAKE_KEY)

    assert result is False, "Should fail when runtime not found and ALLOW_GPM_RUNTIME_SKIP not set"


def test_gpm_runtime_skips_with_allow_skip(monkeypatch):
    """When ALLOW_GPM_RUNTIME_SKIP=true, a missing runtime class returns True."""
    monkeypatch.setenv("ALLOW_GPM_RUNTIME_SKIP", "true")

    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _fake_import(name, *args, **kwargs):
        if name in ("aivan.gpm.runtime", "aivan.gpm.operator_llm_api_runtime"):
            raise ImportError(f"fake: {name}")
        return original_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=_fake_import):
        result = smoke.test_gpm_llm_runtime(_FAKE_KEY)

    assert result is True, "Should skip (return True) when ALLOW_GPM_RUNTIME_SKIP=true"
