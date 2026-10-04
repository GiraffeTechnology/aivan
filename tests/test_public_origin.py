from __future__ import annotations

import pytest

from aivan.observability.public_origin import (
    browser_origin,
    public_origin_issue,
    public_origin_valid,
)

RESERVED = frozenset({9300})


@pytest.mark.parametrize(
    "origin",
    (
        "https://myaivan.test:9100",
        "http://myaivan.test:8080",
        "http://myaivan.test",
        "https://myaivan.test",
    ),
)
def test_public_origin_accepts_any_non_reserved_port(origin):
    assert public_origin_valid(origin, RESERVED), public_origin_issue(origin, RESERVED)


@pytest.mark.parametrize(
    "origin",
    (
        "",
        "https://myaivan.test:9300",
        "http://myaivan.test:9300",
        "https://myaivan.test:9100/app",
        "https://user@myaivan.test:9100",
        "https://MyAivan.test:9100",
        "ftp://myaivan.test:2121",
        "https://myaivan.test:notaport",
    ),
)
def test_public_origin_rejects_reserved_ports_and_non_origins(origin):
    assert not public_origin_valid(origin, RESERVED)


def test_reserved_ports_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("AIVAN_RESERVED_PORTS", "9300, 9301")
    assert not public_origin_valid("https://myaivan.test:9301")
    monkeypatch.setenv("AIVAN_RESERVED_PORTS", "")
    assert public_origin_valid("https://myaivan.test:9301")


def test_browser_origin_drops_only_scheme_default_port():
    assert browser_origin("http://myaivan.test:80") == "http://myaivan.test"
    assert browser_origin("https://myaivan.test:9100") == "https://myaivan.test:9100"
