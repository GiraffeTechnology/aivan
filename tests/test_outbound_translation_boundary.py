from __future__ import annotations

import httpx
import pytest

from aivan.integrations.language_skill_client import LanguageSkillClient
from aivan.integrations.outbound_translation import (
    TranslationUnavailable,
    translate_authoritative_english,
)


def _client(handler) -> LanguageSkillClient:
    return LanguageSkillClient(
        base_url="http://language.test",
        transport=httpx.MockTransport(handler),
    )


def test_dedicated_translator_receives_authoritative_english(monkeypatch):
    monkeypatch.setenv("AIVAN_TRANSLATION_PROOFREAD_ENABLED", "false")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={"provider": "ctranslate2", "model": "opus-mt", "backend": "cpu"},
            )
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "translated_text": "Demande créée.",
                "provider": "ctranslate2",
                "model": "opus-mt",
                "proofreader": {
                    "role": "proofread-only",
                    "status": "accepted",
                    "provider": "ollama",
                    "model": "qwen3.5:9b",
                },
            },
        )

    result = translate_authoritative_english(
        "RFQ created, pending human approval.",
        "fr",
        client=_client(handler),
    )

    assert result.text == "Demande créée."
    assert result.provider == "ctranslate2"
    assert captured["canonical_text"] == "RFQ created, pending human approval."
    assert captured["target_language"] == "fr"
    assert captured["business_refs"]["source_authority"] == "canonical_english"


def test_mock_provider_fails_closed(monkeypatch):
    monkeypatch.setenv("AIVAN_TRANSLATION_PROOFREAD_ENABLED", "false")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"provider": "mock", "models": []})

    with pytest.raises(TranslationUnavailable, match="not production-ready"):
        translate_authoritative_english("English source", "de", client=_client(handler))


def test_generated_targets_cannot_use_chinese_as_source(monkeypatch):
    monkeypatch.setenv("AIVAN_TRANSLATION_PROOFREAD_ENABLED", "false")

    with pytest.raises(ValueError, match="canonical English source"):
        translate_authoritative_english("", "ja", client=_client(lambda _: None))


def test_qwen_proofreader_requires_exact_model(monkeypatch):

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={"provider": "ctranslate2", "model": "opus-mt", "backend": "cpu"},
            )
        return httpx.Response(
            200,
            json={
                "translated_text": "Texto traducido.",
                "provider": "ctranslate2",
                "model": "opus-mt",
                "proofreader": {
                    "role": "proofread-only",
                    "status": "accepted",
                    "provider": "ollama",
                    "model": "qwen3.5:2b",
                },
            },
        )

    with pytest.raises(TranslationUnavailable, match="proofreader boundary"):
        translate_authoritative_english("Translated from English.", "es", client=_client(handler))
