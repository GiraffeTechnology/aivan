from __future__ import annotations

import pytest

from aivan.observability.public_origin import public_origin_issue, public_origin_valid


@pytest.mark.parametrize(
    "origin",
    (
        "https://myaivan.com:8444",
        "https://myaivan.com:9443",
        "http://myaivan.com:8080",
        "http://myaivan.com",
    ),
)
def test_public_origin_accepts_any_port_except_reserved(origin):
    assert public_origin_valid(origin), public_origin_issue(origin)


@pytest.mark.parametrize(
    "origin",
    (
        "",
        "https://myaivan.com",
        "https://myaivan.com:443",
        "http://myaivan.com:443",
        "https://myaivan.com:8443",
        "http://myaivan.com:80",
        "https://myaivan.com:8444/app",
        "https://user@myaivan.com:8444",
        "https://MyAivan.com:8444",
        "ftp://myaivan.com:2121",
        "https://myaivan.com:notaport",
    ),
)
def test_public_origin_rejects_port_443_and_non_origins(origin):
    assert not public_origin_valid(origin)


def test_bare_https_origin_reports_implied_port_443():
    assert "443" in (public_origin_issue("https://myaivan.com") or "")
