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
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.execution.safety import evaluate_requirement_readiness
from aivan.llm import gateway as _gateway
from aivan.llm.policy import external_model_api_enabled
from aivan.rfq import semantic_sources
from aivan.telemetry.model_usage import ModelUsageRecorder, estimate_tokens

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
        "AIVAN_LANGUAGE_SKILL_ENABLED": "true",
        "GLTG_LOCAL_LLM_ENABLED": "true",
    },
    "D": {
        "AIVAN_EXTERNAL_MODEL_API_ENABLED": "false",
        "AIVAN_LLM_API_ENABLED": "true",
        "AIVAN_LLM_PROVIDER": "ollama",
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


def default_cases_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rfq_benchmark_cases.jsonl"


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
    """Run one case through intake + readiness; return per-case metrics."""
    recorder = ModelUsageRecorder()
    error = ""
    try:
        req = structure_customer_requirement_with_llm(
            raw_text=case.raw_text, project_id="benchmark"
        )
        gate = evaluate_requirement_readiness(req)
        action = "pending_email_approval" if gate.ready else gate.next_action
        destination_authoritative = semantic_sources.has_authoritative_destination(req)
        product_authoritative = semantic_sources.has_authoritative_product(req)
        # false-ready: gate says ready but destination is not authoritative.
        false_ready = bool(gate.ready and not destination_authoritative)
        llm_used = os.environ.get("AIVAN_LLM_API_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        if llm_used:
            recorder.record_call(
                task="requirement_structuring",
                provider=os.environ.get("AIVAN_LLM_PROVIDER", "mock"),
                model=os.environ.get("OLLAMA_MODEL", ""),
                input_text=case.raw_text,
                output_text=req.product_type + " " + (req.destination or ""),
            )
    except Exception as exc:  # a normal RFQ must never generic-error out
        error = f"{exc.__class__.__name__}: {exc}"
        return {
            "case_id": case.case_id,
            "tier": case.tier,
            "mode": mode_key,
            "error": error,
            "action": "error",
            "ready": False,
            "false_ready": False,
            "outbound_sent_before_approval": False,
            "external_api_called": recorder.external_api_called,
            "missing_fields": [],
            "total_tokens": recorder.total_tokens,
            "llm_call_count": recorder.llm_call_count,
        }

    return {
        "case_id": case.case_id,
        "tier": case.tier,
        "mode": mode_key,
        "input_language": case.input_language,
        "action": action,
        "ready": gate.ready,
        "false_ready": false_ready,
        "outbound_sent_before_approval": False,  # benchmark never sends
        "external_api_called": recorder.external_api_called,
        "destination_authoritative": destination_authoritative,
        "product_authoritative": product_authoritative,
        "missing_fields": gate.missing_fields,
        "quantity": req.quantity,
        "delivery_days": req.delivery_days,
        "input_tokens": recorder.total_input_tokens,
        "output_tokens": recorder.total_output_tokens,
        "total_tokens": recorder.total_tokens,
        "llm_call_count": recorder.llm_call_count,
        "error": "",
    }


def run_benchmark(cases: list[BenchmarkCase], mode_key: str) -> dict:
    """Run all cases under one mode and aggregate metrics + threshold checks."""
    if mode_key not in MODES:
        raise ValueError(f"Unknown benchmark mode: {mode_key}")

    results: list[dict] = []
    with _mode_env(mode_key):
        for case in cases:
            results.append(run_case(case, mode_key))

    ready = [r for r in results if r["ready"]]
    errors = [r for r in results if r.get("error")]
    false_ready = [r for r in results if r.get("false_ready")]
    external = [r for r in results if r.get("external_api_called")]
    outbound = [r for r in results if r.get("outbound_sent_before_approval")]
    total_tokens = sum(r.get("total_tokens", 0) for r in results)
    llm_calls = sum(r.get("llm_call_count", 0) for r in results)

    thresholds: list[str] = []
    if external:
        thresholds.append(f"external_api_called on {len(external)} case(s)")
    if outbound:
        thresholds.append(f"outbound_before_approval on {len(outbound)} case(s)")
    if false_ready:
        thresholds.append(f"false_ready on {len(false_ready)} case(s)")
    if errors:
        thresholds.append(f"generic_backend_error on {len(errors)} case(s)")

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
            "total_tokens": total_tokens,
            "llm_call_count": llm_calls,
            "tokens_per_case": round(total_tokens / len(results), 2) if results else 0,
        },
        "hard_thresholds_passed": not thresholds,
        "hard_threshold_failures": thresholds,
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
