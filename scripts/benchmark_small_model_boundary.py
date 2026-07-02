#!/usr/bin/env python3
"""Small local-model boundary benchmark (PRD §16/§19).

Runs the RFQ benchmark cases through the private-domain intake + readiness
pipeline under modes A/B/C/D, captures quality/efficiency metrics, enforces the
hard product thresholds, and writes JSON + markdown reports.

Daily-development / CTYUN local-only ergonomics:
    --max-cases N          run only the first N (post-filter) cases
    --case-id ID           run only this case (repeatable)
    --progress             print a live per-case line as each case finishes
    --per-case-timeout S   mark any case exceeding S seconds as a failed timeout
    --fail-fast            stop at the first failing case
    incremental results are always streamed to artifacts/benchmark_events.jsonl

Smoke (fast local check against CTYUN qwen3.5:0.8b):
    uv run python scripts/benchmark_small_model_boundary.py \
        --modes C --max-cases 3 --progress --fail-on-threshold

Full release run:
    uv run python scripts/benchmark_small_model_boundary.py \
        --modes C D --progress --fail-on-threshold
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aivan.telemetry.benchmark import (  # noqa: E402
    default_cases_path,
    filter_cases,
    format_progress_line,
    load_cases,
    recommended_config,
    run_benchmark,
    to_markdown,
)

EVENTS_FILENAME = "benchmark_events.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="AIVAN small local-model boundary benchmark")
    parser.add_argument("--modes", nargs="+", default=["A"], help="Benchmark modes to run (A B C D E)")
    parser.add_argument("--cases", default=str(default_cases_path()))
    parser.add_argument("--out", default="artifacts")
    parser.add_argument("--fail-on-threshold", action="store_true",
                        help="Exit non-zero if any hard threshold fails")
    parser.add_argument("--max-cases", type=int, default=None,
                        help="Run only the first N (post-filter) cases")
    parser.add_argument("--case-id", action="append", dest="case_ids", default=None,
                        help="Run only this case id (repeatable)")
    parser.add_argument("--progress", action="store_true",
                        help="Print a live per-case progress line")
    parser.add_argument("--per-case-timeout", type=float, default=None,
                        help="Mark a case exceeding this many seconds as a failed timeout")
    parser.add_argument("--fail-fast", action="store_true",
                        help="Stop at the first failing case")
    parser.add_argument("--max-local-failure-rate", type=float, default=None,
                        help="C/D only: fail if the local-model call-failure rate exceeds this "
                             "fraction (default off — a called-but-failed 0.8b is measured capability, "
                             "not an integrity violation)")
    args = parser.parse_args()

    all_cases = load_cases(args.cases)
    cases = filter_cases(all_cases, case_ids=args.case_ids, max_cases=args.max_cases)
    if not cases:
        print("[error] no cases matched the given filters", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / EVENTS_FILENAME
    # Fresh incremental log so a long CTYUN run is inspectable while in flight.
    events_fh = events_path.open("w", encoding="utf-8")

    def make_on_case():
        def on_case(result: dict) -> None:
            events_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            events_fh.flush()
            os.fsync(events_fh.fileno())
            if args.progress:
                print(format_progress_line(result), flush=True)
        return on_case

    reports: dict[str, dict] = {}
    try:
        for mode in args.modes:
            reports[mode] = run_benchmark(
                cases, mode,
                on_case=make_on_case(),
                per_case_timeout=args.per_case_timeout,
                fail_fast=args.fail_fast,
                max_local_failure_rate=args.max_local_failure_rate,
            )
            if args.fail_fast and reports[mode].get("stopped_early"):
                break
    finally:
        events_fh.close()

    payload = {"reports": reports, "recommendation": recommended_config(reports)}
    (out_dir / "small_model_boundary_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "small_model_boundary_report.md").write_text(to_markdown(reports), encoding="utf-8")

    print(to_markdown(reports))
    print(f"\nincremental events: {events_path}")
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
