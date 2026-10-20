#!/usr/bin/env python3
"""Package the one-file GLTG feasibility repair from the pinned quote release.

Reuse the single-source integrity engine without rebuilding dependencies, UI,
database repairs or other components. Packaging is not deployment acceptance.
"""
from contextlib import contextmanager
from pathlib import Path

import build_ui_outcome_successor as engine


@contextmanager
def feasibility_profile():
    profile = {
        "BASE_SHA256": "9f527e9a2056de46a0d63d7ce648a404198b352c5d401a219ff17c1d9f6d3907",
        "BASE_REVISION": "9d92319dde5fc97ae1e55d97704b6a6cae51c5b6",
        "BASE_TREE": "ee00d371e6fa5704c5a41c7b947dad23275a6bfb",
        "UI_SOURCE": "src/aivan/integrations/gltg.py",
        "UI_TARGET": str(engine.SITE / "aivan/integrations/gltg.py"),
        "BUILD_KIND": "offline-gltg-feasibility-successor",
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
    # Bounded single-command CLI, not a concurrent profile-selection API.
    with feasibility_profile():
        engine.main(description=__doc__)


if __name__ == "__main__":
    main()
