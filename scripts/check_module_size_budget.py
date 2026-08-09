"""Fail CI when known orchestration modules grow back into monoliths."""

from __future__ import annotations

from pathlib import Path


LINE_BUDGETS = {
    Path("src/aivan/api/main.py"): 1400,
    Path("src/aivan/execution/rfq_execution.py"): 1000,
}


def main() -> int:
    failures: list[str] = []
    for path, maximum in LINE_BUDGETS.items():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        print(f"{path}: {line_count}/{maximum} lines")
        if line_count > maximum:
            failures.append(f"{path} has {line_count} lines; budget is {maximum}")
    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
