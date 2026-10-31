"""Consumer rejection regressions, not deployed translation acceptance."""
import json

import httpx
import pytest

from aivan.integrations.language_skill_client import LanguageSkillClient

SPANISH = "Necesito cien camisas de algodon."
ENGLISH = "Please quote one hundred cotton shirts."


def transport(text, validation, calls, *, detected="en", model="passthrough"):
    def handle(request):
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path == "/v1/inbound/normalize":
            return httpx.Response(200, json={
                "canonical_language": "en", "canonical_text": text,
                "language": {"detected": detected, "confidence": 0.99},
                "translation": {"provider": "ctranslate2", "model": model},
                "warnings": [],
            })
        if request.url.path == "/api/language/canonical-db/validate":
            return validation
        raise AssertionError("Invalid canonical text must not reach structuring")
    return httpx.MockTransport(handle)


def test_auto_spanish_mislabelled_as_english_requires_actual_canonical_validation():
    calls = []
    client = LanguageSkillClient(transport=transport(SPANISH, httpx.Response(200, json={
        "valid": False, "violations": [{"reason": "non_english_canonical_value"}],
    }), calls))
    result = client.normalize(SPANISH)
    assert not result.ok and result.data is None
    assert len(calls) == 2
    assert calls[1][1] == {
        "repository": "aivan", "table_name": "aivan_normalized_intake",
        "record": {"canonical_text": SPANISH}, "policy": "standard_english_canonical_db_v1",
    }
    assert SPANISH not in result.error


def test_verified_english_passthrough_preserved():
    calls = []
    client = LanguageSkillClient(transport=transport(ENGLISH, httpx.Response(200, json={
        "valid": True, "violations": [],
    }), calls))
    result = client.normalize(ENGLISH)
    assert result.ok and result.data["canonical_text"] == ENGLISH
    assert len(calls) == 2


@pytest.mark.parametrize("status,body", [
    (404, {}), (503, {}), (302, {}), (200, {}), (200, {"valid": "true", "violations": []}),
    (200, {"valid": True}), (200, {"valid": True, "violations": [{"reason": "uncertain"}]}),
    (200, {"valid": False, "violations": []}), (200, []),
])
def test_missing_or_invalid_validation_fails_closed(status, body):
    client = LanguageSkillClient(transport=transport(ENGLISH, httpx.Response(status, json=body), []))
    result = client.normalize(ENGLISH)
    assert not result.ok and result.data is None
    assert result.error == "language-skill could not verify canonical English"


@pytest.mark.parametrize("detected", ["es", "und", "auto", ""])
def test_non_english_or_uncertain_passthrough_rejected(detected):
    client = LanguageSkillClient(transport=transport(SPANISH, httpx.Response(200, json={
        "valid": True, "violations": [],
    }), [], detected=detected))
    assert not client.normalize(SPANISH).ok


def test_invalid_latin_passthrough_has_zero_workflow_and_business_effects(monkeypatch, db_session):
    from types import SimpleNamespace
    from aivan.execution import rfq_execution
    from aivan.integrations import language_skill_client
    from aivan.integrations.language_skill import LanguageNormalizationRequired
    from aivan.openclaw.contracts import OpenClawEvent
    from aivan.db.models import Project, ExecutionEventRecord
    from aivan.agents.trade_salesperson_agent import handle_trade_salesperson_event
    import aivan.api.main  # Initialize the application before attachment route helpers.
    from aivan.api.attachment_routes import _input_content
    from tests.test_required_language_intake import upload

    calls, business = [], []
    monkeypatch.setattr(language_skill_client, "_DEFAULT_TRANSPORT", transport(
        SPANISH, httpx.Response(200, json={"valid": False, "violations": []}), calls))
    monkeypatch.setattr(rfq_execution, "classify_event", lambda *args: business.append(True))
    event = OpenClawEvent(tenant_id="test_tenant", message_id="spanish-unverified",
                         conversation_id="spanish-unverified", message_text=SPANISH)
    with pytest.raises(LanguageNormalizationRequired):
        rfq_execution.create_rfq_from_event(event, db_session)
    with pytest.raises(LanguageNormalizationRequired):
        handle_trade_salesperson_event(event, db_session)
    with pytest.raises(LanguageNormalizationRequired):
        _input_content(upload(SPANISH), SimpleNamespace(tenant_id="test_tenant"))
    assert not business and not db_session.new and not db_session.dirty
    assert db_session.query(Project).count() == db_session.query(ExecutionEventRecord).count() == 0
    assert [path for path, _ in calls] == [
        "/v1/inbound/normalize", "/api/language/canonical-db/validate",
    ] * 3


def test_validation_timeout_is_sanitized_and_never_falls_back():
    def handle(request):
        if request.url.path.endswith("/validate"):
            raise httpx.ReadTimeout("untrusted private service details", request=request)
        return httpx.Response(200, json={"canonical_language": "en", "canonical_text": ENGLISH,
                                        "language": {"detected": "en", "confidence": 0.99}})
    result = LanguageSkillClient(transport=httpx.MockTransport(handle)).normalize(ENGLISH)
    assert not result.ok and result.data is None
    assert result.error == "language-skill could not verify canonical English"


def test_explicit_foreign_hint_cannot_be_silently_relabelled_english():
    calls = []
    client = LanguageSkillClient(transport=transport(ENGLISH, httpx.Response(200, json={
        "valid": True, "violations": [],
    }), calls))
    assert not client.normalize(SPANISH, source_language="es").ok
    assert len(calls) == 1


def test_translated_foreign_input_requires_verified_english_output():
    calls = []
    client = LanguageSkillClient(transport=transport(ENGLISH, httpx.Response(200, json={
        "valid": True, "violations": [],
    }), calls, detected="es", model="synthetic-translation-fixture"))
    result = client.normalize(SPANISH, source_language="es")
    assert result.ok and result.data["canonical_text"] == ENGLISH
    assert len(calls) == 2


@pytest.mark.parametrize("language", [None, {}, {"detected": "en"},
    {"detected": "en", "confidence": True}, {"detected": "en", "confidence": 0.1},
    {"detected": "en", "confidence": 2}, {"detected": "en", "confidence": float("nan")},
    {"detected": "und", "confidence": 0.99},
])
def test_missing_or_uncertain_detection_cannot_enter_validation_or_business(language):
    calls = []
    def handle(request):
        calls.append(request.url.path)
        # json.dumps would reject NaN in HTTPX; a manually encoded response
        # exercises the malformed external envelope instead.
        body = json.dumps({"canonical_language": "en", "canonical_text": ENGLISH,
                           "language": language})
        return httpx.Response(200, content=body)
    result = LanguageSkillClient(transport=httpx.MockTransport(handle)).normalize(ENGLISH)
    assert not result.ok and result.data is None
    assert calls == ["/v1/inbound/normalize"]
