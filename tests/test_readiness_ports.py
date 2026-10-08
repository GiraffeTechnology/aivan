from __future__ import annotations

import pytest

from aivan.observability import readiness


@pytest.mark.parametrize("port", ["1", "443", "8443", "9444", "65535"])
@pytest.mark.parametrize("reserved", [None, "", "2222, 3306"])
def test_readiness_allows_valid_unreserved_deployment_ports(monkeypatch, port, reserved):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_PORT", port)
    if reserved is None:
        monkeypatch.delenv("AIVAN_RESERVED_PORTS", raising=False)
    else:
        monkeypatch.setenv("AIVAN_RESERVED_PORTS", reserved)
    monkeypatch.setattr(readiness, "run_dependency_probes", lambda **_: [])

    assert readiness.readiness_checks()["protected_ports_avoided"] is True


@pytest.mark.parametrize(
    ("port", "reserved"),
    [
        ("443", "443"),
        ("8443", "443,8443"),
        ("9444", "9444,2222"),
        ("", ""),
        ("0", ""),
        ("65536", ""),
        ("443.0", ""),
        ("0443", ""),
        ("443", "0"),
        ("443", "65536"),
        ("443", "02222"),
        ("443", "ssh"),
        ("443", "2222,"),
        ("443", "2222,,3306"),
    ],
)
def test_readiness_rejects_reserved_or_invalid_deployment_ports(monkeypatch, port, reserved):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_PORT", port)
    monkeypatch.setenv("AIVAN_RESERVED_PORTS", reserved)
    monkeypatch.setattr(readiness, "run_dependency_probes", lambda **_: [])

    assert readiness.readiness_checks()["protected_ports_avoided"] is False
