"""Rendering a recipient reply cannot mutate the canonical DB result."""
import copy
import json

import httpx
import pytest

from aivan.api.main import _skill_response
from aivan.integrations import language_skill_client
from aivan.integrations.language_skill_client import LanguageSkillClient
from aivan.integrations.outbound_translation import translate_authoritative_english
from tests.test_operator_reply_renderer import _result


@pytest.mark.parametrize("language", ["zh", "zht", "fr", "es", "de", "ko", "ja"])
def test_recipient_generation_is_ephemeral_and_dedicated(language):
    requests = []
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"provider": "ctranslate2", "model": "opus-mt", "backend": "cpu"})
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"translated_text": "Recipient fixture text", "provider": "ctranslate2", "model": "opus-mt"})
    language_skill_client.set_default_transport(httpx.MockTransport(handler))
    try:
        result = _result("pending_requirement_confirmation", {
            "language": "en", "raw_text": "Please quote shirts", "extra": {"requested_output_language": language},
        }, [], user_message="Please confirm the quantity.")
        before = copy.deepcopy(result.model_dump())
        rendered = _skill_response(result)
        assert rendered["reply_text"] == "Recipient fixture text"
        assert result.model_dump() == before
        assert rendered["user_control_message"] == "Please confirm the quantity."
        assert requests[0]["canonical_text"] == "Please confirm the quantity."
        assert requests[0]["target_language"] == language
    finally:
        language_skill_client.set_default_transport(None)


def test_translation_unavailable_keeps_complete_english(monkeypatch):
    from aivan.integrations import skill_reply
    from aivan.integrations.outbound_translation import TranslationUnavailable
    def unavailable(*a, **k):
        raise TranslationUnavailable("stable failure")
    monkeypatch.setattr(skill_reply, "translate_authoritative_english", unavailable)
    result = _result("pending_requirement_confirmation", {"language": "zh"}, [], "Confirm quantity.")
    assert _skill_response(result)["reply_text"] == "Confirm quantity."


@pytest.mark.parametrize("status", [201, 204, 301, 302, 307, 503])
def test_language_http_outcomes_do_not_echo_raw_response_or_follow_redirects(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "http://redirect.test/"}, json={"secret": "private-source"})
    client = LanguageSkillClient(transport=httpx.MockTransport(handler))
    result = client.normalize("Private input")
    assert result.ok is False
    assert result.data is None
    assert "private-source" not in result.error
    assert len(calls) == 1


def test_chinese_business_output_uses_same_generator_boundary():
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"provider": "qwen", "model": "qwen3.5:9b", "backend": "ollama"})
        pytest.fail("untrusted generator must not be invoked")
    from aivan.integrations.outbound_translation import TranslationUnavailable
    with pytest.raises(TranslationUnavailable):
        translate_authoritative_english("English source", "zh", client=LanguageSkillClient(transport=httpx.MockTransport(handler)))
