"""Multilingual UI tests for myaivan.

English is the system/canonical language. en/zh catalogs are built in; other
languages are translated through giraffe-language-skill (/v1/outbound/render)
and fail soft to English. The default UI language follows the visitor's
system/browser language, switchable anytime via the 🌐 selector.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from aivan.integrations import language_skill_client
from aivan.web import i18n

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "aivan" / "app" / "static"
TEMPLATES = ROOT / "src" / "aivan" / "app" / "templates"


@pytest.fixture(autouse=True)
def _fresh_cache():
    i18n.clear_cache()
    yield
    i18n.clear_cache()


# ── builtin catalogs ──────────────────────────────────────────────────────────

def test_english_is_canonical_builtin(api_client):
    data = api_client.get("/api/myaivan/i18n/en").json()
    assert data["lang"] == "en"
    assert data["source"] == "builtin"
    assert data["strings"]["welcome.title"].startswith("Welcome back")
    assert set(data["languages"]) >= {"en", "zh", "ja", "es", "fr"}


def test_zh_builtin_and_region_tags_normalize(api_client):
    for tag in ("zh", "zh-CN", "zh_TW"):
        data = api_client.get(f"/api/myaivan/i18n/{tag}").json()
        assert data["lang"] == "zh"
        assert data["source"] == "builtin"
        assert "欢迎回来" in data["strings"]["welcome.title"]


def test_zh_catalog_covers_every_english_key():
    assert set(i18n.CATALOG_ZH) == set(i18n.CATALOG_EN)


def test_unknown_language_normalizes_to_english(api_client):
    data = api_client.get("/api/myaivan/i18n/klingon").json()
    assert data["lang"] == "en"
    assert data["source"] == "builtin"


# ── language-skill translation path ───────────────────────────────────────────

def _render_transport(prefix: str = "[ja] "):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/outbound/render":
            import json

            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "rendered_text": prefix + payload["canonical_text"],
                    "target_language": payload["target_language"],
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handle)


def test_other_language_translated_via_language_skill(api_client, monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    language_skill_client.set_default_transport(_render_transport())
    try:
        data = api_client.get("/api/myaivan/i18n/ja").json()
    finally:
        language_skill_client.set_default_transport(None)
    assert data["lang"] == "ja"
    assert data["source"] == "language_skill"
    assert data["strings"]["welcome.title"] == "[ja] " + i18n.CATALOG_EN["welcome.title"]
    # Translated catalogs are cached — the next call must not hit the network.
    cached = api_client.get("/api/myaivan/i18n/ja").json()
    assert cached["strings"]["welcome.title"].startswith("[ja] ")


def test_language_skill_unavailable_falls_back_to_english(api_client, monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    language_skill_client.set_default_transport(
        httpx.MockTransport(lambda req: httpx.Response(503, json={"detail": "down"}))
    )
    try:
        data = api_client.get("/api/myaivan/i18n/ja").json()
    finally:
        language_skill_client.set_default_transport(None)
    assert data["lang"] == "ja"
    assert data["source"] == "fallback_en"
    assert data["strings"] == i18n.CATALOG_EN


def test_language_skill_disabled_falls_back_to_english(api_client, monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    data = api_client.get("/api/myaivan/i18n/ja").json()
    assert data["source"] == "fallback_en"
    assert data["strings"]["welcome.title"] == i18n.CATALOG_EN["welcome.title"]


# ── UI wiring ─────────────────────────────────────────────────────────────────

def test_language_switcher_on_both_pages(api_client):
    for path in ("/myaivan", "/myaivan/work"):
        html = api_client.get(path).text
        assert 'id="lang-select"' in html, f"{path} missing language switcher"
        assert "🌐" in html, f"{path} missing language icon"
        assert "myaivan-i18n.js" in html


def test_default_language_follows_system_language():
    js = (STATIC / "myaivan-i18n.js").read_text()
    assert "navigator.language" in js       # system-language default
    assert "myaivan.lang" in js             # persisted user override
    assert "data-i18n" in js


def test_templates_use_english_canonical_markup():
    for name in ("myaivan_welcome.html", "myaivan_work.html"):
        html = (TEMPLATES / name).read_text()
        assert 'data-i18n=' in html
        # Canonical markup is English; other languages come from catalogs.
        assert "Welcome back" in html or "Outbound review" in html
