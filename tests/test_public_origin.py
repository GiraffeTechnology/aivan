from __future__ import annotations

import pytest

from aivan.observability.public_origin import (
    browser_origin,
    public_origin_issue,
    public_origin_valid,
)


@pytest.mark.parametrize(
    "origin",
    (
        "https://myaivan.test:9100",
        "https://myaivan.test:8443",
        "http://myaivan.test:8080",
        "http://myaivan.test:80",
    ),
)
def test_public_origin_accepts_any_explicit_port_except_443(origin):
    assert public_origin_valid(origin), public_origin_issue(origin)


@pytest.mark.parametrize(
    "origin",
    (
        "",
        "https://myaivan.test",
        "http://myaivan.test",
        "https://myaivan.test:443",
        "http://myaivan.test:443",
        "https://myaivan.test:9100/app",
        "https://user@myaivan.test:9100",
        "https://MyAivan.test:9100",
        "ftp://myaivan.test:2121",
        "https://myaivan.test:notaport",
    ),
)
def test_public_origin_rejects_implied_or_443_port_and_non_origins(origin):
    assert not public_origin_valid(origin)


def test_missing_port_is_reported_explicitly():
    assert "port" in (public_origin_issue("https://myaivan.test") or "")


def test_browser_origin_drops_only_scheme_default_port():
    assert browser_origin("http://myaivan.test:80") == "http://myaivan.test"
    assert browser_origin("https://myaivan.test:9100") == "https://myaivan.test:9100"
