#!/usr/bin/env python3
"""Package the one-file quote-price repair from the pinned read-isolation release.

Reuse the existing single-source integrity engine and all of its closed-world
checks. No dependency, database, controller, UI or other component is rebuilt.
This command packages bytes; it does not install or accept a deployed workflow.
"""
from contextlib import contextmanager
from pathlib import Path

import build_ui_outcome_successor as engine


@contextmanager
def quote_profile():
    # Historical engine constant names remain for compatibility; this bounded
    # CLI profile selects the quote source, never an arbitrary caller path.
    profile = {
        "BASE_SHA256": "d27b7126bac1049e51d36c651992e1ed64e155e0d5f4ce9e879a8d4103c680d9",
        "BASE_REVISION": "1932885324a895030b6e5b284e36be577edc2291",
        "BASE_TREE": "92fc20ae2aa1942d432bde05a2329420723575a7",
        "UI_SOURCE": "src/aivan/agents/buyer_option_agent.py",
        "UI_TARGET": str(engine.SITE / "aivan/agents/buyer_option_agent.py"),
        "BUILD_KIND": "offline-quote-price-validity-successor",
        "PROFILE_SHA256": engine.build.digest(Path(__file__)),
    }
    original = {key: getattr(engine, key) for key in profile}
    try:
        for key, value in profile.items():
            setattr(engine, key, value)
        yield engine
    finally:
        for key, value in original.items():
            setattr(engine, key, value)


def main():
    # This is a single-command CLI, not a concurrent profile-selection API.
    with quote_profile():
        engine.main(description=__doc__)


if __name__ == "__main__":
    main()
