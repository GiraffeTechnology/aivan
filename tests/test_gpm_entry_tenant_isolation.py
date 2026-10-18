"""API tenant-isolation unit checks with synthetic services/SQLite, not E2E."""
import json

import httpx
import pytest

from aivan.db.models.project import Project
from aivan.integrations import gpm_guidance_client
from tests.test_rfq_execution_iteration import (  # noqa: F401
    _customer_email_event, _explicit_unit_supplier_dataset,
    _language_skill_resolves_canonical_fields, api_client, api_db,
)


@pytest.mark.parametrize('entry', ['native', 'standard'])
def test_other_tenant_case_reference_cannot_reach_gpm(api_client, api_db, monkeypatch, entry):
    owner, caller = 'entry-tenant-owner', 'entry-tenant-caller'
    monkeypatch.delenv('AIVAN_API_KEY', raising=False)
    monkeypatch.delenv('AIVAN_TENANT_ID', raising=False)
    monkeypatch.setenv('AIVAN_TENANT_API_KEYS', json.dumps({owner: 'synthetic-owner-key', caller: 'synthetic-caller-key'}))
    def headers(tenant, key):
        return {'X-AIVAN-API-Key': key, 'X-AIVAN-Tenant-ID': tenant,
                'X-AIVAN-Actor-ID': 'entry-operator', 'X-AIVAN-Role-Context': 'admin',
                'X-AIVAN-Execution-Mode': 'approval'}
    owner_headers = headers(owner, 'synthetic-owner-key')
    created = api_client.post('/api/rfq/create-from-event', json=_customer_email_event(), headers=owner_headers)
    assert created.status_code == 200, created.text
    case_id = created.json()['project_id']
    before = api_client.get('/api/projects/' + case_id, headers=owner_headers).json()
    count = api_db.query(Project).count()
    requests = []
    def forbidden(request):
        requests.append(request)
        raise AssertionError('Foreign case must not reach the advisory provider')
    monkeypatch.setattr(gpm_guidance_client, '_DEFAULT_TRANSPORT', httpx.MockTransport(forbidden))
    text = 'USD 4.50/pc, MOQ 5000 pcs, daily capacity 500 pcs, lead time 35 days, FOB Guangzhou.'
    context = {'channel': 'wechat', 'sender_id': 'supplier_001', 'project_id': case_id,
               'role_context': 'supplier', 'mode': 'auto', 'message_id': 'foreign-case-reply'}
    if entry == 'standard':
        path = '/invoke'
        body = {'session_id': 'foreign-case-thread', 'user_input': text, 'context': context}
    else:
        path = '/api/openclaw/events'
        body = {'source': 'openclaw', 'conversation_id': 'foreign-case-thread', 'message_text': text, **context}
    response = api_client.post(path, json=body, headers=headers(caller, 'synthetic-caller-key'))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['status'] == 'error', payload
    assert 'buyer_options_ready' not in response.text
    assert case_id not in response.text and owner not in response.text
    assert payload['reply_text'] == payload['output']
    assert not requests
    assert api_db.query(Project).count() == count
    assert api_client.get('/api/projects/' + case_id, headers=owner_headers).json() == before
    assert api_client.get('/api/projects/' + case_id, headers=headers(caller, 'synthetic-caller-key')).status_code == 404


@pytest.mark.parametrize('path', ['/invoke', '/api/openclaw/events'])
def test_native_body_tenant_impersonation_rejected_before_execution(api_client, api_db, monkeypatch, path):
    caller = 'entry-tenant-caller'
    monkeypatch.delenv('AIVAN_API_KEY', raising=False)
    monkeypatch.delenv('AIVAN_TENANT_ID', raising=False)
    monkeypatch.setenv('AIVAN_TENANT_API_KEYS', json.dumps({caller: 'synthetic-caller-key'}))
    headers = {'X-AIVAN-API-Key': 'synthetic-caller-key', 'X-AIVAN-Tenant-ID': caller,
               'X-AIVAN-Actor-ID': 'entry-operator', 'X-AIVAN-Role-Context': 'admin'}
    body = {**_customer_email_event(), 'tenant_id': 'foreign-body-tenant'}
    before = api_db.query(Project).count()
    response = api_client.post(path, headers=headers, json=body)
    assert response.status_code == 403, response.text
    assert response.json()['detail']['error'] == 'TENANT_MISMATCH'
    assert api_db.query(Project).count() == before
