"""HTTP 200 is not proof of canonical-English normalization."""
from __future__ import annotations

import httpx
import pytest

from aivan.integrations.language_skill_client import LanguageSkillClient


@pytest.mark.parametrize("changes", [
    {"canonical_text": "SYNTHETIC TEST: 请报价100件棉质T恤，送往上海。"},
    {"canonical_language": "zh"},
    {"canonical_text": ""},
    {"canonical_text": None},
    {"translation": {"provider": "ctranslate2", "model": "unavailable"}},
    {"warnings": [{"code": "TRANSLATION_MODEL_MISSING", "field": "translation", "message": "Unavailable"}]},
])
def test_normalize_rejects_invalid_canonical_response(changes):
    response = {"canonical_language": "en", "canonical_text": "Need 100 cotton shirts.", **changes}
    client = LanguageSkillClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)))
    result = client.normalize("Synthetic inquiry", canonical_language="en")
    assert result.ok is False
    assert result.data is None
    assert result.status_code == 200
    assert result.error == "language-skill returned invalid canonical result"


def test_normalize_preserves_english_unicode_punctuation_and_latin_names():
    text = "Please quote Café uniforms — 100 units for René."
    client = LanguageSkillClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"canonical_language": "en", "canonical_text": text})))
    result = client.normalize("Synthetic inquiry")
    assert result.ok is True
    assert result.data["canonical_text"] == text


def test_invalid_200_normalize_stops_workflow_and_business_writes(monkeypatch, db_session):
    from aivan.execution import rfq_execution
    from aivan.integrations import language_skill_client
    from aivan.openclaw.contracts import OpenClawEvent

    calls = []
    raw = "SYNTHETIC TEST: 请报价100件棉质T恤，送往上海。"
    def transport(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"canonical_language": "en", "canonical_text": raw})
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_FAIL_SOFT", "true")
    monkeypatch.setattr(language_skill_client, "_DEFAULT_TRANSPORT", httpx.MockTransport(transport))
    classified = []
    monkeypatch.setattr(rfq_execution, "classify_event", lambda *a: classified.append(True))
    with pytest.raises(Exception, match="LANGUAGE_NORMALIZATION_REQUIRED"):
        rfq_execution.create_rfq_from_event(OpenClawEvent(
            tenant_id="unit-tenant", conversation_id="synthetic-normalize-failure", message_text=raw), db_session)
    assert calls == ["/v1/inbound/normalize"]
    assert classified == [] and not db_session.new and not db_session.dirty
