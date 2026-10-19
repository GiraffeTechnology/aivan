from __future__ import annotations

import pytest

from aivan.observability import readiness


@pytest.mark.parametrize("expected,actual,valid", [
    ("", "", False), ("", "example-route", False),
    ("example-route", "", False), ("example-route", "different-route", False),
    ("example-route", "example-route", True),
    ("second-route", "second-route", True),
])
def test_readiness_requires_configured_egress_agreement(monkeypatch, expected, actual, valid):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_EXPECTED_EGRESS_POLICY", expected)
    monkeypatch.setenv("AIVAN_NON_CHINA_EGRESS_POLICY", actual)
    monkeypatch.setattr(readiness, "run_dependency_probes", lambda **_: [])
    checks = readiness.readiness_checks()
    assert checks["non_china_policy_declared"] is valid
