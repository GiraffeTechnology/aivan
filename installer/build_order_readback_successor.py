#!/usr/bin/env python3
"""Package the one-file order readback repair from the pinned feasibility release.

Reuse the single-source integrity engine without rebuilding dependencies, UI,
database repairs or other components. Packaging is not deployment acceptance.
"""
from contextlib import contextmanager
from pathlib import Path

import build_ui_outcome_successor as engine


@contextmanager
def order_readback_profile():
    profile = {
        "BASE_SHA256": "e2b39884b7af6a2f654cacbd5713d9c30d89f3ddd004a1098d865e9f05e2265d",
        "BASE_REVISION": "4e66685f8594394cdd7ab81695ba4c658b0f6c82",
        "BASE_TREE": "11792a215427b49ae607531c943bf564b16bc4e2",
        "UI_SOURCE": "src/aivan/integrations/order_confirmation.py",
        "UI_TARGET": str(engine.SITE / "aivan/integrations/order_confirmation.py"),
        "BUILD_KIND": "offline-order-readback-successor",
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
    with order_readback_profile():
        engine.main(description=__doc__)


if __name__ == "__main__":
    main()
