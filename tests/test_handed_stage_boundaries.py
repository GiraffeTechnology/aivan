"""Synthetic boundary tests, not real provider or customer-send acceptance."""
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from aivan.agents.supplier_material_reply import (
    SupplierMaterialContextError, material_context, parse_material_declarations,
)
from aivan.integrations.gltg import GLTGClient
from aivan.integrations.execution_association import ExecutionAssociationReader, ExecutionAssociationError
from aivan.openclaw.client import OpenClawClient
from aivan.openclaw.contracts import OpenClawSendRequest
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.schemas.rfq import RFQStrategy


TEXT = ('Material availability: partial_stock; raw material lead time: 2.75 days; '
        'Material lock required: false; execution mode: trader; material can be locked: yes')


def test_material_exact_values_and_source_without_guesses():
    fields = parse_material_declarations(TEXT)['fields']
    assert fields['material_lock_required']['value'] is False
    assert fields['raw_material_lead_time_estimate_days']['value'] == 2.75
    assert fields['raw_material_lead_time_estimate_days']['source_text'] == 'raw material lead time: 2.75 days'
    original = {'source_observation_ids': ['observation-fixture']}
    result = material_context(original, SimpleNamespace(raw_text=TEXT))
    assert result['trade_processing_factors'] == {
        'material': {'material_availability_status': 'partial_stock',
                     'raw_material_lead_time_estimate_days': 2.75, 'material_lock_required': False},
        'supplier_execution': {'supplier_execution_mode': 'trader'},
    }
    assert original == {'source_observation_ids': ['observation-fixture']}
    assert result['source_observation_ids'] == ['observation-fixture']


@pytest.mark.parametrize('text', [
    'Raw material lead time: 2-4 days', 'Raw material lead time: -2 days',
    'We might have raw material in stock', 'Material lock required: probably',
])
def test_ambiguous_material_does_not_become_provider_fact(text):
    assert parse_material_declarations(text)['fields'] == {}
    assert material_context({}, SimpleNamespace(raw_text=text))['trade_processing_factors'] == {}


@pytest.mark.parametrize('context,text', [
    ({}, 'Material lock required: true; Material lock required: false'),
    ({'trade_processing_factors': {'material': {'material_lock_required': True}}},
     'Material lock required: false'),
])
def test_material_conflicts_are_not_overwritten(context, text):
    original = deepcopy(context)
    with pytest.raises(SupplierMaterialContextError):
        material_context(context, SimpleNamespace(raw_text=text))
    assert context == original


@pytest.mark.parametrize('operation', ['simulate', 'estimate'])
def test_supplier_material_reaches_actual_v2_request(monkeypatch, operation):
    monkeypatch.setenv('GLTG_API_VERSION', 'v2')
    calls = []
    class Provider:
        def simulate_lead_time_v2(self, payload):
            calls.append(payload)
            return SimpleNamespace(ok=True, error=None, data={
                'ok': True, 'quantiles': {'p50_days': 4.25, 'p80_days': 6.5, 'p90_days': 8.75},
                'risk': {'deadline_risk_level': 'low', 'deadline_feasible': True},
            })
    client = GLTGClient(http=Provider())
    requirement = BuyerRequirement(project_id='case-fixture', quantity=100, delivery_days=12)
    reply = SupplierReply(project_id='case-fixture', supplier_id='supplier-fixture', raw_text=TEXT)
    if operation == 'simulate':
        client.simulate(requirement, RFQStrategy(), supplier_count=1, supplier_id='supplier-fixture',
                        tenant_id='tenant-fixture', supplier_reply=reply)
    else:
        client.estimate_for_requirement(requirement, supplier_reply=reply, tenant_id='tenant-fixture')
    assert len(calls) == 1
    assert calls[0]['tenant_id'] == 'tenant-fixture'
    assert calls[0]['supplier']['supplier_id'] == 'supplier-fixture'
    assert calls[0]['trade_processing_factors']['material']['material_lock_required'] is False
    assert calls[0]['trade_processing_factors']['material']['raw_material_lead_time_estimate_days'] == 2.75


def test_openclaw_mock_never_claims_delivery_or_connection(monkeypatch):
    monkeypatch.setenv('OPENCLAW_MOCK_MODE', 'true')
    client = OpenClawClient()
    result = client.send_message(OpenClawSendRequest(channel='fixture', conversation_id='case-fixture',
        target_peer_id='synthetic-peer', message_text='synthetic, not sent'))
    assert result.success is False and result.outcome_uncertain is False
    assert result.message_id == result.sent_at == ''
    assert client.check_account_status('synthetic-account')['status'] != 'connected'


def test_openclaw_account_failure_does_not_expose_exception(monkeypatch):
    monkeypatch.setenv('OPENCLAW_MOCK_MODE', 'false')
    monkeypatch.setenv('OPENCLAW_BASE_URL', 'https://transport.invalid')
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic-private-token-and-response-body')
    monkeypatch.setattr(httpx, 'get', fail)
    assert OpenClawClient().check_account_status('fixture') == {
        'status': 'error', 'error': 'OPENCLAW_ACCOUNT_STATUS_UNAVAILABLE'}


def association_fixture():
    state = {'schema_version': 'abcdYi.execution.v1', 'source_po_id': 'po-fixture',
             'source_quote_id': 'quote-fixture', 'source_snapshot_hash': 'a' * 64,
             'local_order_id': '11111111-1111-4111-8111-111111111111',
             'local_project_id': '22222222-2222-4222-8222-222222222222'}
    order = {'tenant_id': 'tenant-fixture', 'po_id': 'po-fixture', 'procurement_case_id': 'case-ref',
             'rfq_id': 'rfq-fixture', 'selected_quote_id': 'quote-fixture', 'status': 'confirmed',
             'source_snapshot_hash': 'a' * 64, 'execution_revision': 1,
             'metadata_json': {'aivan_project_id': 'case-fixture', 'abcdyi_execution': state}}
    envelope = {'tenant_id': 'tenant-fixture', 'po_id': 'po-fixture', 'revision': 1,
                'source_snapshot_hash': 'a' * 64, 'state': state}
    confirmation = {'status': 'confirmed', 'purchase_order_id': 'po-fixture',
                    'supplier_quote_id': 'quote-fixture', 'procurement_case_id': 'case-ref', 'rfq_id': 'rfq-fixture'}
    graph = {'procurement_case_id': 'case-ref', 'rfq_id': 'rfq-fixture'}
    return order, envelope, confirmation, graph


@pytest.mark.parametrize('change', ['none', 'tenant', 'case', 'revision-drift'])
def test_association_reads_validate_identity_and_never_enable_unrouted_execution(change):
    order, envelope, confirmation, graph = association_fixture()
    latest = deepcopy(order)
    if change == 'tenant': order['tenant_id'] = 'other-tenant'
    if change == 'case': order['metadata_json']['aivan_project_id'] = 'other-case'
    if change == 'revision-drift': latest['execution_revision'] = 2
    responses = iter([order, envelope, latest])
    calls = []
    class Provider:
        tenant_id = 'tenant-fixture'
        def _request(self, method, path):
            calls.append((method, path))
            return httpx.Response(200, json=next(responses))
    reader = ExecutionAssociationReader(Provider())
    if change == 'none':
        result = reader.read(case_id='case-fixture', confirmation=confirmation, graph=graph)
        assert result['status'] == 'associated' and result['readback_verified'] is True
        assert result['execution_reads_available'] is False
        assert len(calls) == 3
    else:
        with pytest.raises(ExecutionAssociationError) as caught:
            reader.read(case_id='case-fixture', confirmation=confirmation, graph=graph)
        assert caught.value.status == (409 if change == 'revision-drift' else 404)
    assert all(method == 'GET' for method, _ in calls)
