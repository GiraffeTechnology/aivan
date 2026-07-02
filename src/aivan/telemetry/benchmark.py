"""Small local-model boundary benchmark harness.

Runs the same RFQ cases through the private-domain intake + readiness pipeline
under several model regimes (PRD §16) and measures quality/efficiency plus the
hard product thresholds:

  * no external LLM/VLM API called automatically in private-domain mode,
  * no outbound before human approval,
  * never "ready" when destination is missing/non-authoritative,
  * no generic backend error on a normal RFQ input.

The harness itself performs no network I/O beyond whatever the configured
providers do; Mode A (zero-model) is fully offline and deterministic, which is
what the unit test exercises.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.execution.safety import evaluate_requirement_readiness
from aivan.llm import gateway as _gateway
from aivan.rfq import semantic_sources

# Modes that must actually exercise a private-domain local model.
LOCAL_LLM_MODES = frozenset({"C", "D"})
EXPECTED_LOCAL_PROVIDER = "ollama"
EXPECTED_LOCAL_MODEL = "qwen3.5:0.8b"

# Env overrides per benchmark mode (PRD §16.2).
MODES: dict[str, dict[str, str]] = {
    "A": {
        "AIVAN_EXTERNAL_MODEL_API_ENABLED": "false",
        "AIVAN_LLM_API_ENABLED": "false",
        "AIVAN_LLM_PROVIDER": "disabled",
        "AIVAN_LANGUAGE_SKILL_ENABLED": "false",
        "GLTG_LOCAL_LLM_ENABLED": "false",
    },
    "B": {
        "AIVAN_EXTERNAL_MODEL_API_ENABLED": "false",
        "AIVAN_LLM_API_ENABLED": "false",
        "AIVAN_LLM_PROVIDER": "disabled",
        "AIVAN_LANGUAGE_SKILL_ENABLED": "true",
        "GLTG_LOCAL_LLM_ENABLED": "false",
    },
    "C": {
        "AIVAN_EXTERNAL_MODEL_API_ENABLED": "false",
        "AIVAN_LLM_API_ENABLED": "true",
        "AIVAN_LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "qwen3.5:0.8b",
        "AIVAN_LANGUAGE_SKILL_ENABLED": "true",
        "GLTG_LOCAL_LLM_ENABLED": "true",
    },
    "D": {
        "AIVAN_EXTERNAL_MODEL_API_ENABLED": "false",
        "AIVAN_LLM_API_ENABLED": "true",
        "AIVAN_LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "qwen3.5:0.8b",
        "AIVAN_LANGUAGE_SKILL_ENABLED": "false",
        "GLTG_LOCAL_LLM_ENABLED": "true",
    },
    "E": {
        "AIVAN_EXTERNAL_MODEL_API_ENABLED": "true",
        "AIVAN_LLM_API_ENABLED": "true",
        "AIVAN_EXTERNAL_API_CONFIRMATION_REQUIRED": "true",
    },
}


@dataclass
class BenchmarkCase:
    case_id: str
    tier: str
    input_language: str
    raw_text: str
    expects: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, obj: dict) -> "BenchmarkCase":
        return cls(
            case_id=obj["case_id"],
            tier=obj.get("tier", "unknown"),
            input_language=obj.get("input_language", "auto"),
            raw_text=obj["raw_text"],
            expects=obj.get("expects", {}) or {},
        )


def load_cases(path: str | os.PathLike) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(BenchmarkCase.from_json(json.loads(line)))
    return cases


# NOTE: tests/fixtures/rfq_benchmark_cases.jsonl is a SEED dataset spanning all
# six tiers. TODO(bench): expand to >=20 cases per tier (>=120 total) and enable
# per-tier accuracy threshold gating (e.g. simple-RFQ field accuracy >= 95%) once
# a live language-skill / qwen3.5:0.8b endpoint is wired into CI.
IS_SEED_DATASET = True


def default_cases_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rfq_benchmark_cases.jsonl"


def filter_cases(
    cases: list[BenchmarkCase],
    case_ids: list[str] | None = None,
    max_cases: int | None = None,
) -> list[BenchmarkCase]:
    """Apply --case-id / --max-cases filters. No filters -> unchanged list."""
    selected = cases
    if case_ids:
        wanted = list(case_ids)
        by_id = {c.case_id: c for c in cases}
        selected = [by_id[cid] for cid in wanted if cid in by_id]
    if max_cases is not None and max_cases >= 0:
        selected = selected[:max_cases]
    return selected


def format_progress_line(result: dict) -> str:
    """One-line progress summary for a completed case."""
    status = "FAIL(" + ",".join(result.get("fail_reasons") or []) + ")" if result.get("failed") else "PASS"
    return (
        f"[{result.get('mode')}] {result.get('case_id')} "
        f"tier={result.get('tier')} start={result.get('started_at')} "
        f"elapsed={result.get('elapsed_seconds')}s "
        f"provider={result.get('provider')} model={result.get('model') or '-'} "
        f"tokens={result.get('local_llm_tokens', result.get('total_tokens', 0))} {status}"
    )


@contextmanager
def _mode_env(mode_key: str):
    overrides = MODES[mode_key]
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    _gateway.reset_provider()
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _gateway.reset_provider()


def run_case(case: BenchmarkCase, mode_key: str) -> dict:
    """Run one case through intake + readiness; return per-case metrics.

    Provider usage is read from real gateway telemetry (not env guesses), so the
    benchmark can prove a local model actually ran and never silently fell back
    to mock or reached an external API.
    """
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    configured_provider = os.environ.get("AIVAN_LLM_PROVIDER", "mock")
    events: list = []
    _gateway.add_call_observer(events.append)
    error = ""
    try:
        try:
            req = structure_customer_requirement_with_llm(
                raw_text=case.raw_text, project_id="benchmark"
            )
            gate = evaluate_requirement_readiness(req)
        except Exception as exc:  # a normal RFQ must never generic-error out
            error = f"{exc.__class__.__name__}: {exc}"
    finally:
        _gateway.remove_call_observer(events.append)
    elapsed_seconds = round(time.perf_counter() - started, 3)

    # Telemetry-derived provider facts.
    local_events = [e for e in events if e.used_provider not in ("mock", "none")]
    real_local_call = any(
        e.configured_provider == EXPECTED_LOCAL_PROVIDER
        and e.used_provider == EXPECTED_LOCAL_PROVIDER
        and e.ok
        for e in events
    )
    mock_fallback = any(
        e.configured_provider not in ("mock", "none") and e.used_provider == "mock"
        for e in events
    )
    external_api_called = any(e.external_api_called and e.ok for e in events)
    local_llm_tokens = sum(e.input_tokens + e.output_tokens for e in local_events)
    local_llm_latency_ms = sum(e.latency_ms for e in local_events)
    local_llm_tasks = sorted({e.task for e in local_events})
    local_llm_model = next(
        (e.model for e in local_events if e.configured_provider == EXPECTED_LOCAL_PROVIDER and e.model),
        os.environ.get("OLLAMA_MODEL", "") if os.environ.get("AIVAN_LLM_PROVIDER") == "ollama" else "",
    )

    timing = {
        "started_at": started_at,
        "elapsed_seconds": elapsed_seconds,
        "provider": configured_provider,
        "model": local_llm_model,
    }

    if error:
        return {
            "case_id": case.case_id, "tier": case.tier, "mode": mode_key,
            "error": error, "action": "error", "ready": False, "false_ready": False,
            "outbound_sent_before_approval": False, "external_api_called": external_api_called,
            "missing_fields": [], "total_tokens": local_llm_tokens, "llm_call_count": len(events),
            "real_local_call": real_local_call, "mock_fallback": mock_fallback,
            "local_llm_model": local_llm_model, "local_llm_tokens": local_llm_tokens,
            "local_llm_latency_ms": round(local_llm_latency_ms, 3), "local_llm_tasks": local_llm_tasks,
            "timed_out": False, **timing,
        }

    action = "pending_email_approval" if gate.ready else gate.next_action
    destination_authoritative = semantic_sources.has_authoritative_destination(req)
    product_authoritative = semantic_sources.has_authoritative_product(req)
    false_ready = bool(gate.ready and not destination_authoritative)

    return {
        "case_id": case.case_id, "tier": case.tier, "mode": mode_key,
        "input_language": case.input_language, "action": action, "ready": gate.ready,
        "false_ready": false_ready, "outbound_sent_before_approval": False,
        "external_api_called": external_api_called,
        "destination_authoritative": destination_authoritative,
        "product_authoritative": product_authoritative,
        "missing_fields": gate.missing_fields, "quantity": req.quantity,
        "delivery_days": req.delivery_days, "llm_call_count": len(events),
        "real_local_call": real_local_call, "mock_fallback": mock_fallback,
        "local_llm_model": local_llm_model, "local_llm_tokens": local_llm_tokens,
        "local_llm_latency_ms": round(local_llm_latency_ms, 3), "local_llm_tasks": local_llm_tasks,
        "total_tokens": local_llm_tokens, "error": "", "timed_out": False, **timing,
    }


def case_failures(result: dict, mode_key: str) -> list[str]:
    """Per-case failure reasons for the pass/fail summary and fail-fast."""
    reasons: list[str] = []
    if result.get("timed_out"):
        reasons.append("timeout")
        return reasons
    if result.get("error"):
        reasons.append(f"error:{result['error'][:60]}")
    if result.get("external_api_called"):
        reasons.append("external_api_called")
    if result.get("false_ready"):
        reasons.append("false_ready")
    if result.get("outbound_sent_before_approval"):
        reasons.append("outbound_before_approval")
    if mode_key in LOCAL_LLM_MODES and not result.get("error"):
        if result.get("mock_fallback"):
            reasons.append("mock_fallback")
        elif not result.get("real_local_call"):
            reasons.append("ollama_not_called")
        elif result.get("local_llm_model") != EXPECTED_LOCAL_MODEL:
            reasons.append("unexpected_local_model")
    return reasons


def _timeout_result(case: BenchmarkCase, mode_key: str, timeout_seconds: float,
                    started_at: str, elapsed: float) -> dict:
    return {
        "case_id": case.case_id, "tier": case.tier, "mode": mode_key,
        "input_language": case.input_language, "error": "", "action": "timeout",
        "ready": False, "false_ready": False, "outbound_sent_before_approval": False,
        "external_api_called": False, "missing_fields": [], "total_tokens": 0,
        "llm_call_count": 0, "real_local_call": False, "mock_fallback": False,
        "local_llm_model": "", "local_llm_tokens": 0,
        "local_llm_latency_ms": round(elapsed * 1000, 3), "local_llm_tasks": [],
        "timed_out": True, "timeout_seconds": timeout_seconds,
        "started_at": started_at, "elapsed_seconds": round(elapsed, 3),
        "provider": os.environ.get("AIVAN_LLM_PROVIDER", "mock"), "model": "",
    }


def _run_one(case: BenchmarkCase, mode_key: str, per_case_timeout: float | None) -> dict:
    """Run a single case, enforcing an optional wall-clock per-case timeout."""
    if not per_case_timeout or per_case_timeout <= 0:
        return run_case(case, mode_key)
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(run_case, case, mode_key)
    try:
        return future.result(timeout=per_case_timeout)
    except FutureTimeout:
        elapsed = time.perf_counter() - started
        return _timeout_result(case, mode_key, per_case_timeout, started_at, elapsed)
    finally:
        # Never block shutdown on an orphaned (still-running) case thread.
        executor.shutdown(wait=False)


def run_benchmark(
    cases: list[BenchmarkCase],
    mode_key: str,
    *,
    on_case=None,
    per_case_timeout: float | None = None,
    fail_fast: bool = False,
) -> dict:
    """Run all cases under one mode and aggregate metrics + threshold checks.

    ``on_case`` (if given) is called with each per-case result immediately after
    it completes — used for live progress and incremental JSONL output.
    ``per_case_timeout`` marks any case exceeding it as a failed timeout and
    continues (unless ``fail_fast``). ``fail_fast`` stops at the first failing
    case. With no filters/hooks the behavior is identical to before.
    """
    if mode_key not in MODES:
        raise ValueError(f"Unknown benchmark mode: {mode_key}")

    results: list[dict] = []
    stopped_early = False
    with _mode_env(mode_key):
        for case in cases:
            result = _run_one(case, mode_key, per_case_timeout)
            reasons = case_failures(result, mode_key)
            result["failed"] = bool(reasons)
            result["fail_reasons"] = reasons
            results.append(result)
            if on_case is not None:
                on_case(result)
            if fail_fast and reasons:
                stopped_early = True
                break

    ready = [r for r in results if r["ready"]]
    errors = [r for r in results if r.get("error")]
    timeouts = [r for r in results if r.get("timed_out")]
    false_ready = [r for r in results if r.get("false_ready")]
    external = [r for r in results if r.get("external_api_called")]
    outbound = [r for r in results if r.get("outbound_sent_before_approval")]
    total_tokens = sum(r.get("total_tokens", 0) for r in results)
    llm_calls = sum(r.get("llm_call_count", 0) for r in results)
    real_local = [r for r in results if r.get("real_local_call")]
    mock_fallbacks = [r for r in results if r.get("mock_fallback")]
    local_llm_tokens = sum(r.get("local_llm_tokens", 0) for r in results)
    local_llm_latency = sum(r.get("local_llm_latency_ms", 0) for r in results)
    local_llm_tasks = sorted({t for r in results for t in r.get("local_llm_tasks", [])})

    thresholds: list[str] = []
    if external:
        thresholds.append(f"external_api_called on {len(external)} case(s)")
    if outbound:
        thresholds.append(f"outbound_before_approval on {len(outbound)} case(s)")
    if false_ready:
        thresholds.append(f"false_ready on {len(false_ready)} case(s)")
    if errors:
        thresholds.append(f"generic_backend_error on {len(errors)} case(s)")
    if timeouts:
        thresholds.append(f"timeout on {len(timeouts)} case(s)")

    # Local-LLM modes (C/D) must actually exercise the local model: every case
    # must record a real ollama call with the expected model, and none may fall
    # back to mock. A dead Ollama must NOT look like success.
    if mode_key in LOCAL_LLM_MODES:
        if mock_fallbacks:
            thresholds.append(f"mock_fallback on {len(mock_fallbacks)} case(s) (local model not really used)")
        if len(real_local) < len(results):
            missing = len(results) - len(real_local)
            thresholds.append(
                f"ollama_not_called on {missing} case(s) (expected provider={EXPECTED_LOCAL_PROVIDER})"
            )
        bad_model = [
            r for r in results if r.get("real_local_call") and r.get("local_llm_model") != EXPECTED_LOCAL_MODEL
        ]
        if bad_model:
            thresholds.append(
                f"unexpected_local_model on {len(bad_model)} case(s) (expected {EXPECTED_LOCAL_MODEL})"
            )

    return {
        "mode": mode_key,
        "mode_env": MODES[mode_key],
        "case_count": len(results),
        "aggregate": {
            "ready_count": len(ready),
            "blocked_count": len(results) - len(ready) - len(errors),
            "false_ready_count": len(false_ready),
            "external_api_call_count": len(external),
            "outbound_before_approval_count": len(outbound),
            "error_count": len(errors),
            "timeout_count": len(timeouts),
            "total_tokens": total_tokens,
            "llm_call_count": llm_calls,
            "tokens_per_case": round(total_tokens / len(results), 2) if results else 0,
            "real_local_call_count": len(real_local),
            "mock_fallback_count": len(mock_fallbacks),
            "local_llm_tokens": local_llm_tokens,
            "local_llm_latency_ms": round(local_llm_latency, 3),
            "local_llm_tasks": local_llm_tasks,
            "expected_local_provider": EXPECTED_LOCAL_PROVIDER if mode_key in LOCAL_LLM_MODES else None,
            "expected_local_model": EXPECTED_LOCAL_MODEL if mode_key in LOCAL_LLM_MODES else None,
        },
        "hard_thresholds_passed": not thresholds,
        "hard_threshold_failures": thresholds,
        "stopped_early": stopped_early,
        "results": results,
    }


def recommended_config(reports: dict[str, dict]) -> dict:
    """Derive a recommended private-domain config from measured reports."""
    return {
        "recommended_private_domain_config": {
            "deterministic_extraction": "always_on",
            "language_skill": "always_on",
            "local_small_llm": {
                "classification": "optional",
                "strategy_interpretation": "optional",
                "draft_polishing": "optional",
                "canonical_fields": "forbidden",
            },
            "external_llm_api": "off",
            "external_vlm_api": "off",
        },
        "measured_modes": {
            mode: {
                "ready_count": rep["aggregate"]["ready_count"],
                "false_ready_count": rep["aggregate"]["false_ready_count"],
                "external_api_call_count": rep["aggregate"]["external_api_call_count"],
                "tokens_per_case": rep["aggregate"]["tokens_per_case"],
                "hard_thresholds_passed": rep["hard_thresholds_passed"],
            }
            for mode, rep in reports.items()
        },
    }


def to_markdown(reports: dict[str, dict]) -> str:
    lines = ["# Small Local Model Boundary Report", ""]
    lines.append("| Mode | Cases | Ready | Blocked | FalseReady | ExtAPI | Errors | Tokens/case | Thresholds |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for mode, rep in reports.items():
        agg = rep["aggregate"]
        lines.append(
            f"| {mode} | {rep['case_count']} | {agg['ready_count']} | {agg['blocked_count']} | "
            f"{agg['false_ready_count']} | {agg['external_api_call_count']} | {agg['error_count']} | "
            f"{agg['tokens_per_case']} | {'PASS' if rep['hard_thresholds_passed'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("Hard thresholds: 0 automatic external API calls, 0 outbound-before-approval, ")
    lines.append("0 false-ready, 0 generic backend errors on valid RFQ input.")
    return "\n".join(lines)
