"""Compatibility vectors for the shared OpenClaw invoke-body adapter."""
from copy import deepcopy

import pytest

from aivan.api import main as api


def test_native_event_is_copied_without_discarding_followup_fields():
    raw = {'message_text': 'Synthetic reply', 'project_id': 'case-one',
           'role_context': 'supplier', 'conversation_id': 'conversation-one'}
    before = deepcopy(raw)
    result = api._normalize_invoke_payload(raw)
    assert result == raw and result is not raw
    assert raw == before


def test_standard_skill_preserves_explicit_context_and_source_body():
    raw = {'session_id': ' conversation-one ', 'user_input': 'Synthetic reply',
           'context': {'channel': ' email ', 'sender_id': ' supplier-one ',
                       'project_id': 'case-one', 'role_context': 'supplier', 'mode': ' manual '}}
    before = deepcopy(raw)
    assert api._normalize_invoke_payload(raw) == {
        'source': 'openclaw', 'channel': 'email', 'conversation_id': 'conversation-one',
        'sender_id': 'supplier-one', 'message_text': 'Synthetic reply', 'message_type': 'text',
        'mode': 'manual', 'project_id': 'case-one', 'role_context': 'supplier',
    }
    assert raw == before


@pytest.mark.parametrize('context', [None, [], 'not-a-context'])
def test_missing_context_keeps_existing_generated_identifier_defaults(monkeypatch, context):
    monkeypatch.setattr(api.uuid, 'uuid4', lambda: 'synthetic-generated-conversation')
    result = api._normalize_invoke_payload({'user_input': 'RFQ', 'context': context})
    assert result == {'source': 'openclaw', 'channel': 'openclaw',
                      'conversation_id': 'synthetic-generated-conversation',
                      'sender_id': 'openclaw-user', 'message_text': 'RFQ',
                      'message_type': 'text', 'mode': 'auto'}


def test_webhook_keeps_existing_sender_room_and_message_type_mapping():
    assert api._normalize_invoke_payload({'content': 'Synthetic reply', 'from_user': ' supplier-one ',
                                         'room_id': ' room-one ', 'msg_type': ' text '}) == {
        'source': 'wechat', 'channel': 'wechat', 'conversation_id': 'room-one',
        'sender_id': 'supplier-one', 'message_text': 'Synthetic reply',
        'message_type': 'text', 'mode': 'auto'}


@pytest.mark.parametrize('value', [None, [], 'text'])
def test_non_object_payload_is_still_rejected(value):
    with pytest.raises(ValueError, match='JSON object'):
        api._normalize_invoke_payload(value)


def test_unknown_shape_still_fails_without_reinterpreting_its_fields():
    with pytest.raises(ValueError, match='unrecognized payload keys'):
        api._normalize_invoke_payload({'unsupported': 'Synthetic value'})
