"""ASGI entry-to-consumer unit checks with synthetic services/SQLite, not E2E."""
import json

import httpx
import pytest

from aivan.execution import rfq_execution
from aivan.db.models.project import Project
from aivan.integrations import gpm_guidance_client
from tests.gpm_guidance_fake import mock_transport
from tests.test_rfq_execution_iteration import (  # noqa: F401
    _customer_email_event, _explicit_unit_supplier_dataset,
    _language_skill_resolves_canonical_fields, api_client, api_db,
)


@pytest.mark.parametrize('tenant', ['entry-tenant-alpha', 'entry-tenant-beta'])
@pytest.mark.parametrize('entry', ['native', 'standard'])
def test_authenticated_entry_preserves_tenant_through_supplier_reply_and_gpm(api_client, monkeypatch, tenant, entry):
    # Exercise request-scoped key-map handling, different from conftest's
    # fallback tenant. All keys/endpoints here are synthetic unit fixtures.
    monkeypatch.delenv('AIVAN_API_KEY', raising=False)
    monkeypatch.delenv('AIVAN_TENANT_ID', raising=False)
    monkeypatch.setenv('AIVAN_TENANT_API_KEYS', json.dumps({tenant: 'synthetic-entry-key'}))
    monkeypatch.setenv('GPM_TENANT_API_KEYS', json.dumps({tenant: 'synthetic-gpm-tenant-key'}))
    headers = {'X-AIVAN-API-Key': 'synthetic-entry-key', 'X-AIVAN-Tenant-ID': tenant, 'X-AIVAN-Actor-ID': 'entry-operator',
               'X-AIVAN-Role-Context': 'admin', 'X-AIVAN-Execution-Mode': 'approval',
               'X-AIVAN-Trace-ID': 'entry-trace'}
    contexts, requests = [], []
    real = rfq_execution._create_stage1_gpm_guidance
    def capture(**kwargs):
        contexts.append((kwargs['project'].tenant_id, kwargs['event'].tenant_id,
                         kwargs['event'].authenticated_actor_id))
        return real(**kwargs)
    monkeypatch.setattr(rfq_execution, '_create_stage1_gpm_guidance', capture)
    response_transport = mock_transport()
    def downstream(request):
        requests.append(request)
        return response_transport.handle_request(request)
    monkeypatch.setattr(gpm_guidance_client, '_DEFAULT_TRANSPORT', httpx.MockTransport(downstream))
    created = api_client.post('/api/rfq/create-from-event', json=_customer_email_event(), headers=headers)
    assert created.status_code == 200, created.text
    case_id = created.json()['project_id']
    text = 'USD 4.50/pc, MOQ 5000 pcs, daily capacity 500 pcs, lead time 35 days, FOB Guangzhou.'
    context = {'channel': 'wechat', 'sender_id': 'supplier_001', 'project_id': case_id,
               'role_context': 'supplier', 'mode': 'auto', 'message_id': 'entry-supplier-reply'}
    if entry == 'standard':
        path = '/invoke'
        body = {'session_id': 'entry-supplier-thread', 'user_input': text, 'context': context}
    else:
        path = '/api/openclaw/events'
        body = {'source': 'openclaw', 'conversation_id': 'entry-supplier-thread',
                'message_text': text, **context}
    response = api_client.post(path, json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['action'] == 'buyer_options_ready', response.text
    assert contexts == [(tenant, tenant, 'entry-operator')]
    assert len(requests) == 1
    request = requests[0]
    assert request.headers['X-AIVAN-Tenant-ID'] == tenant
    assert request.headers['X-AIVAN-API-Key'] == 'synthetic-gpm-tenant-key'
    assert request.headers['X-AIVAN-Actor-ID'] == 'entry-operator'
    assert json.loads(request.content)['case_id'] == case_id
    stored = api_client.get('/api/projects/' + case_id, headers=headers)
    assert stored.status_code == 200
    assert stored.json()['requirement']['gpm_guidance']['packet_id']


@pytest.mark.parametrize('body_tenant', [None, 'body-only-tenant'])
def test_missing_request_tenant_is_rejected_before_case_creation(api_client, api_db, monkeypatch, body_tenant):
    tenant = 'entry-tenant-alpha'
    monkeypatch.delenv('AIVAN_API_KEY', raising=False)
    monkeypatch.delenv('AIVAN_TENANT_ID', raising=False)
    monkeypatch.setenv('AIVAN_TENANT_API_KEYS', json.dumps({tenant: 'synthetic-entry-key'}))
    headers = {'X-AIVAN-API-Key': 'synthetic-entry-key', 'X-AIVAN-Actor-ID': 'entry-operator',
               'X-AIVAN-Role-Context': 'admin', 'X-AIVAN-Execution-Mode': 'approval'}
    before = api_db.query(Project).count()
    body = _customer_email_event()
    if body_tenant is not None:
        body['tenant_id'] = body_tenant
    response = api_client.post('/api/rfq/create-from-event', headers=headers, json=body)
    assert response.status_code == 400
    assert response.json()['detail']['error'] == 'TENANT_REQUIRED'
    assert api_db.query(Project).count() == before
