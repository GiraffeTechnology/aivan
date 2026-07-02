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
    # In modes C/D the RFQ structuring step is model-required, so every case is
    # expected to attempt a local qwen3.5:0.8b call. A fixture may set
    # ``llm_required: false`` to declare a deterministic/no-model-needed case;
    # then an absent local call is intentionally_skipped, not a missing call.
    llm_required: bool = True

    @classmethod
    def from_json(cls, obj: dict) -> "BenchmarkCase":
        return cls(
            case_id=obj["case_id"],
            tier=obj.get("tier", "unknown"),
            input_language=obj.get("input_language", "auto"),
            raw_text=obj["raw_text"],
            expects=obj.get("expects", {}) or {},
            llm_required=bool(obj.get("llm_required", True)),
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

    # Telemetry-derived provider facts. Read entirely from the gateway events —
    # never inferred from env (env is only a display default when NO call fired).
    local_events = [e for e in events if e.used_provider not in ("mock", "none")]
    # The structuring call is the model-required task for a benchmark case.
    struct_events = [e for e in events if e.task == "requirement_structuring"] or events
    primary = struct_events[-1] if struct_events else None

    if primary is not None:
        used_provider = primary.used_provider
        provider_ok = bool(primary.ok)
        provider_error = primary.error or ""
        fell_back_to_mock = bool(primary.fell_back_to_mock)
        primary_external = bool(primary.external_api_called and primary.ok)
        primary_model = primary.model or ""
        # Not "invoked" when the gateway short-circuited (llm disabled / no provider).
        llm_invoked = primary.used_provider != "none"
    else:
        used_provider = "none"
        provider_ok = False
        provider_error = ""
        fell_back_to_mock = False
        primary_external = False
        primary_model = ""
        llm_invoked = False

    mock_fallback = any(
        e.configured_provider not in ("mock", "none") and e.used_provider == "mock"
        for e in events
    ) or fell_back_to_mock
    external_api_called = any(e.external_api_called and e.ok for e in events) or primary_external
    local_llm_tokens = sum(e.input_tokens + e.output_tokens for e in local_events)
    local_llm_latency_ms = sum(e.latency_ms for e in local_events)
    local_llm_tasks = sorted({e.task for e in local_events})
    local_llm_model = primary_model or next(
        (e.model for e in local_events if e.configured_provider == EXPECTED_LOCAL_PROVIDER and e.model),
        "",
    )

    # Classify the local-model outcome for modes C/D (n/a for A/B/E).
    real_local_call = bool(
        llm_invoked and used_provider == EXPECTED_LOCAL_PROVIDER and provider_ok
    )
    if mode_key not in LOCAL_LLM_MODES:
        local_call_status = "n/a"
        llm_skipped_reason = ""
    elif not llm_invoked:
        # No local call fired at all. Distinguish an intentional deterministic
        # skip from a model-required call that went missing.
        llm_skipped_reason = provider_error or ("no_llm_invoked" if primary is None else "")
        if not case.llm_required:
            local_call_status = "intentionally_skipped"
        else:
            local_call_status = "expected_local_call_missing"
    elif mock_fallback:
        local_call_status = "mock_fallback"
        llm_skipped_reason = ""
    elif used_provider != EXPECTED_LOCAL_PROVIDER:
        local_call_status = "wrong_provider"
        llm_skipped_reason = ""
    elif not provider_ok:
        local_call_status = "local_call_failed"
        llm_skipped_reason = ""
    elif local_llm_model != EXPECTED_LOCAL_MODEL:
        local_call_status = "unexpected_local_model"
        llm_skipped_reason = ""
    else:
        local_call_status = "real_local_call"
        llm_skipped_reason = ""

    telemetry = {
        "configured_provider": (primary.configured_provider if primary else configured_provider),
        "used_provider": used_provider,
        "provider_ok": provider_ok,
        "provider_error": provider_error,
        "fell_back_to_mock": fell_back_to_mock,
        "external_api_called": external_api_called,
        "llm_invoked": llm_invoked,
        "llm_skipped_reason": llm_skipped_reason,
        "local_call_status": local_call_status,
    }

    timing = {
        "started_at": started_at,
        "elapsed_seconds": elapsed_seconds,
        "provider": (primary.configured_provider if primary else configured_provider),
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
            "timed_out": False, **telemetry, **timing,
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
        "total_tokens": local_llm_tokens, "error": "", "timed_out": False,
        **telemetry, **timing,
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
        status = result.get("local_call_status", "")
        # Integrity failures (block merge). A local_call_failed (the model was
        # exercised but the 0.8b model could not produce valid output) is a
        # measured capability datapoint, NOT an integrity failure — reported, not
        # a per-case hard fail. intentionally_skipped is allowed by definition.
        if status in {"mock_fallback", "expected_local_call_missing",
                      "wrong_provider", "unexpected_local_model"}:
            reasons.append(status)
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
        "configured_provider": os.environ.get("AIVAN_LLM_PROVIDER", "mock"),
        "used_provider": "none", "provider_ok": False, "provider_error": "timeout",
        "fell_back_to_mock": False, "llm_invoked": False, "llm_skipped_reason": "timeout",
        "local_call_status": "timeout",
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
    max_local_failure_rate: float | None = None,
) -> dict:
    """Run all cases under one mode and aggregate metrics + threshold checks.

    ``on_case`` (if given) is called with each per-case result immediately after
    it completes — used for live progress and incremental JSONL output.
    ``per_case_timeout`` marks any case exceeding it as a failed timeout and
    continues (unless ``fail_fast``). ``fail_fast`` stops at the first failing
    case. ``max_local_failure_rate`` optionally gates the local-model
    call-failure rate (default off — a called-but-failed 0.8b is measured
    capability, not an integrity violation). With no filters/hooks the behavior
    is identical to before.
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
    local_llm_tokens = sum(r.get("local_llm_tokens", 0) for r in results)
    local_llm_latency = sum(r.get("local_llm_latency_ms", 0) for r in results)
    local_llm_tasks = sorted({t for r in results for t in r.get("local_llm_tasks", [])})

    # Local-model outcome breakdown from per-case telemetry (never env).
    by_status: dict[str, list[dict]] = {}
    for r in results:
        by_status.setdefault(r.get("local_call_status", "n/a"), []).append(r)
    real_local = by_status.get("real_local_call", [])
    local_failed = by_status.get("local_call_failed", [])
    expected_missing = by_status.get("expected_local_call_missing", [])
    intentionally_skipped = by_status.get("intentionally_skipped", [])
    unexpected_model = by_status.get("unexpected_local_model", [])
    wrong_provider = by_status.get("wrong_provider", [])
    mock_fallbacks = [r for r in results if r.get("mock_fallback")]
    attempts = len(real_local) + len(local_failed)
    local_failure_rate = round(len(local_failed) / attempts, 4) if attempts else 0.0
    # Model-required cases = every non-skipped, non-timeout, non-error C/D case.
    model_required = (
        real_local + local_failed + expected_missing + unexpected_model
        + wrong_provider + mock_fallbacks
    )

    # ── INTEGRITY gate (private-domain safety; always blocks --fail-on-threshold)
    # These are breaches of the private-domain contract, never model quality:
    #   external API, silent mock fallback, outbound-before-approval, false-ready,
    #   generic backend error, timeout, and (C/D) a model-required case that never
    #   attempted the local call, the wrong provider/model, or Ollama never once
    #   succeeding (0 successful calls = effectively dead).
    integrity_failures: list[str] = []
    if external:
        integrity_failures.append(f"external_api_call_count>0 ({len(external)} case(s))")
    if outbound:
        integrity_failures.append(f"outbound_before_approval_count>0 ({len(outbound)} case(s))")
    if false_ready:
        integrity_failures.append(f"false_ready_count>0 ({len(false_ready)} case(s))")
    if errors:
        integrity_failures.append(f"generic_backend_error>0 ({len(errors)} case(s))")
    if timeouts:
        integrity_failures.append(f"timeout>0 ({len(timeouts)} case(s))")
    if mode_key in LOCAL_LLM_MODES:
        if mock_fallbacks:
            integrity_failures.append(
                f"mock_fallback_count>0 ({len(mock_fallbacks)} case(s); local model silently replaced by mock)"
            )
        if expected_missing:
            integrity_failures.append(
                f"expected_local_call_missing>0 ({len(expected_missing)} case(s); "
                f"model-required case never attempted a {EXPECTED_LOCAL_PROVIDER} call)"
            )
        if wrong_provider:
            integrity_failures.append(
                f"wrong_provider>0 ({len(wrong_provider)} case(s); expected {EXPECTED_LOCAL_PROVIDER})"
            )
        if unexpected_model:
            integrity_failures.append(
                f"unexpected_local_model>0 ({len(unexpected_model)} case(s); expected {EXPECTED_LOCAL_MODEL})"
            )
        if model_required and not real_local:
            integrity_failures.append(
                f"real_local_call_count==0 in Mode {mode_key} "
                f"(0/{len(model_required)} real {EXPECTED_LOCAL_PROVIDER} calls; check endpoint/model)"
            )

    # ── CAPABILITY gate (model quality; report-only unless --max-local-failure-rate)
    # local_call_failed = qwen3.5:0.8b was genuinely attempted but returned
    # unparseable output. This is a measured capability limitation, NOT a
    # private-domain integrity breach, so it never fails the default gate.
    local_call_failed_cases = [
        {"case_id": r.get("case_id"), "tier": r.get("tier"),
         "error": (r.get("provider_error") or "")[:120]}
        for r in local_failed
    ]
    capability_failures: list[str] = []
    if mode_key not in LOCAL_LLM_MODES:
        capability_status = "n/a"
    elif max_local_failure_rate is None:
        capability_status = "report_only"
    elif local_failure_rate > max_local_failure_rate:
        capability_status = "fail"
        capability_failures.append(
            f"local_call_failure_rate {local_failure_rate:.2%} exceeds "
            f"max {max_local_failure_rate:.2%} ({len(local_failed)}/{attempts} calls failed)"
        )
    else:
        capability_status = "pass"

    integrity_status = "pass" if not integrity_failures else "fail"
    all_failures = integrity_failures + capability_failures

    return {
        "mode": mode_key,
        "mode_env": MODES[mode_key],
        "case_count": len(results),
        "integrity_status": integrity_status,
        "integrity_failures": integrity_failures,
        "capability_status": capability_status,
        "capability_failures": capability_failures,
        "local_call_failure_rate": local_failure_rate,
        "local_call_failed_cases": local_call_failed_cases,
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
            "local_call_failed_count": len(local_failed),
            "expected_local_call_missing_count": len(expected_missing),
            "intentionally_skipped_local_call_count": len(intentionally_skipped),
            "unexpected_local_model_count": len(unexpected_model),
            "wrong_provider_count": len(wrong_provider),
            "mock_fallback_count": len(mock_fallbacks),
            "local_call_attempts": attempts,
            "local_call_failure_rate": local_failure_rate,
            "local_llm_tokens": local_llm_tokens,
            "local_llm_latency_ms": round(local_llm_latency, 3),
            "local_llm_tasks": local_llm_tasks,
            "expected_local_provider": EXPECTED_LOCAL_PROVIDER if mode_key in LOCAL_LLM_MODES else None,
            "expected_local_model": EXPECTED_LOCAL_MODEL if mode_key in LOCAL_LLM_MODES else None,
        },
        "hard_thresholds_passed": not all_failures,
        "hard_threshold_failures": all_failures,
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
                "integrity_status": rep.get("integrity_status"),
                "capability_status": rep.get("capability_status"),
                "local_call_failure_rate": rep.get("local_call_failure_rate"),
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

    # Integrity vs capability status per mode (explicitly separated).
    lines.append("")
    lines.append("## Integrity vs capability")
    lines.append("| Mode | integrity_status | capability_status | local_call_failure_rate |")
    lines.append("|---|---|---|---|")
    for mode, rep in reports.items():
        lines.append(
            f"| {mode} | {rep.get('integrity_status')} | {rep.get('capability_status')} | "
            f"{rep.get('local_call_failure_rate', 0.0):.2%} |"
        )
    lines.append("")
    lines.append("integrity_status gates the merge (--fail-on-threshold). capability_status is")
    lines.append("report-only unless --max-local-failure-rate is passed; local_call_failed means")
    lines.append("qwen3.5:0.8b was attempted but returned unparseable output (model capability),")
    lines.append("not a private-domain integrity breach.")

    # Local-model outcome breakdown + per-case provider telemetry for C/D.
    for mode, rep in reports.items():
        if mode not in LOCAL_LLM_MODES:
            continue
        agg = rep["aggregate"]
        lines.append("")
        lines.append(f"## Mode {mode} — local model outcome breakdown")
        lines.append(
            f"integrity_status={rep.get('integrity_status')}, "
            f"capability_status={rep.get('capability_status')}, "
            f"real_local_call={agg['real_local_call_count']}, "
            f"local_call_failed={agg['local_call_failed_count']} "
            f"(rate {agg['local_call_failure_rate']:.2%}), "
            f"expected_local_call_missing={agg['expected_local_call_missing_count']}, "
            f"intentionally_skipped={agg['intentionally_skipped_local_call_count']}, "
            f"mock_fallback={agg['mock_fallback_count']}, "
            f"unexpected_model={agg['unexpected_local_model_count']}"
        )
        if rep.get("integrity_failures"):
            lines.append("Integrity failures: " + "; ".join(rep["integrity_failures"]))
        if rep.get("capability_failures"):
            lines.append("Capability failures: " + "; ".join(rep["capability_failures"]))
        failed_cases = rep.get("local_call_failed_cases") or []
        if failed_cases:
            listed = ", ".join(f"{c['case_id']}({c['tier']})" for c in failed_cases)
            lines.append(f"local_call_failed case IDs: {listed}")
        lines.append("")
        lines.append("### Per-case provider telemetry")
        lines.append(
            "| case_id | tier | status | configured | used | model | ok | fell_back | external | error |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in rep["results"]:
            lines.append(
                f"| {r.get('case_id')} | {r.get('tier')} | {r.get('local_call_status','')} | "
                f"{r.get('configured_provider','')} | {r.get('used_provider','')} | "
                f"{r.get('model') or '-'} | {r.get('provider_ok')} | {r.get('fell_back_to_mock')} | "
                f"{r.get('external_api_called')} | {(r.get('provider_error') or '')[:60]} |"
            )
    return "\n".join(lines)
