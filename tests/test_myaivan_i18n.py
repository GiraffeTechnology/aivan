"""Multilingual UI tests for MyAIVAN.

English is the system/canonical language. en/zh catalogs are built in and are
the only offered languages until production translation returns real localized
strings. The default UI language follows the visitor's system/browser language,
switchable anytime via the 🌐 selector.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
    assert data["strings"]["welcome.tagline"].startswith("MyAIVAN is")
    assert data["languages"] == {"en": "English", "zh": "中文"}


def test_zh_builtin_and_region_tags_normalize(api_client):
    for tag in ("zh", "zh-CN", "zh_TW"):
        data = api_client.get(f"/api/myaivan/i18n/{tag}").json()
        assert data["lang"] == "zh"
        assert data["source"] == "builtin"
        assert "欢迎回来" in data["strings"]["welcome.title"]
        assert data["strings"]["welcome.tagline"].startswith("MyAIVAN 是")


def test_zh_catalog_covers_every_english_key():
    assert set(i18n.CATALOG_ZH) == set(i18n.CATALOG_EN)


def test_unavailable_language_normalizes_to_english(api_client):
    data = api_client.get("/api/myaivan/i18n/ja").json()
    assert data["lang"] == "en"
    assert data["source"] == "builtin"


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
