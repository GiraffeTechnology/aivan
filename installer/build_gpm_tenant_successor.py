#!/usr/bin/env python3
"""Package the one-file GPM tenant repair from the pinned order-readback release.

Reuse the single-source integrity engine without rebuilding dependencies, UI,
database repairs or other components. Packaging is not deployment acceptance.
"""
from contextlib import contextmanager
from pathlib import Path

import build_ui_outcome_successor as engine


@contextmanager
def gpm_tenant_profile():
    profile = {
        "BASE_SHA256": "3beef41ca931f6254a6aad555dfd1ef353e0cebfda4b07eff4a10d8946d95e94",
        "BASE_REVISION": "00636c8ad45f2485dc05245835013529fbaf75f9",
        "BASE_TREE": "0b159a6073ae873620b44d5b1af609d0f42ccfd4",
        "UI_SOURCE": "src/aivan/execution/gpm_guidance.py",
        "UI_TARGET": str(engine.SITE / "aivan/execution/gpm_guidance.py"),
        "BUILD_KIND": "offline-gpm-tenant-successor",
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
    with gpm_tenant_profile():
        engine.main(description=__doc__)


if __name__ == "__main__":
    main()
