#!/usr/bin/env python3
"""Small local-model boundary benchmark (PRD §16/§19).

Runs the RFQ benchmark cases through the private-domain intake + readiness
pipeline under modes A/B/C/D, captures quality/efficiency metrics, enforces the
hard product thresholds, and writes JSON + markdown reports.

Usage:
    uv run python scripts/benchmark_small_model_boundary.py [--modes A B C D]
        [--cases tests/fixtures/rfq_benchmark_cases.jsonl] [--out artifacts]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aivan.telemetry.benchmark import (  # noqa: E402
    load_cases,
    default_cases_path,
    recommended_config,
    run_benchmark,
    to_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="AIVAN small local-model boundary benchmark")
    parser.add_argument("--modes", nargs="+", default=["A"], help="Benchmark modes to run (A B C D E)")
    parser.add_argument("--cases", default=str(default_cases_path()))
    parser.add_argument("--out", default="artifacts")
    parser.add_argument("--fail-on-threshold", action="store_true", help="Exit non-zero if any hard threshold fails")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    reports: dict[str, dict] = {}
    for mode in args.modes:
        reports[mode] = run_benchmark(cases, mode)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"reports": reports, "recommendation": recommended_config(reports)}
    (out_dir / "small_model_boundary_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "small_model_boundary_report.md").write_text(to_markdown(reports), encoding="utf-8")

    print(to_markdown(reports))
    any_failed = any(not rep["hard_thresholds_passed"] for rep in reports.values())
    if any_failed:
        for mode, rep in reports.items():
            if not rep["hard_thresholds_passed"]:
                print(f"[FAIL] mode {mode}: {rep['hard_threshold_failures']}", file=sys.stderr)
        if args.fail_on_threshold:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
