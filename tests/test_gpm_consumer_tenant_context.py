"""Synthetic orchestration-boundary checks; no real GPM or DB acceptance."""
from types import SimpleNamespace

import pytest
import httpx

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.execution.gpm_guidance import create_stage1_gpm_guidance
from aivan.integrations.gpm_guidance_client import GPMGuidanceClient, GPMGuidanceUnavailableError
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def invoke(monkeypatch, project_tenant, event_tenant, *, real_transport=False):
    calls = []
    def create(self, **kwargs):
        calls.append(kwargs)
        return {'packet_id': 'synthetic-packet', 'recommendation': 'review', 'confidence': 'medium'}
    if real_transport:
        from aivan.integrations import gpm_guidance_client
        monkeypatch.setenv('AIVAN_ENV', 'local')
        monkeypatch.setenv('GPM_API_KEY', 'synthetic-transport-key')
        monkeypatch.delenv('GPM_TENANT_API_KEYS', raising=False)
        def handle(request):
            calls.append(request)
            return httpx.Response(503, json={'private': 'synthetic downstream body'})
        monkeypatch.setattr(gpm_guidance_client, '_DEFAULT_TRANSPORT', httpx.MockTransport(handle))
    else:
        monkeypatch.setattr(GPMGuidanceClient, 'create_guidance', create)
    requirement = BuyerRequirement(project_id='case-1', quantity=100)
    reply = SupplierReply(project_id='case-1', supplier_id='supplier-1', unit_price=12,
                          currency='GBP', raw_text='Synthetic quote GBP 12')
    option = generate_buyer_options(requirement, [reply], [], 'case-1')[0]
    def run():
        return create_stage1_gpm_guidance(
            project=SimpleNamespace(tenant_id=project_tenant, project_id='case-1'),
            event=OpenClawEvent(tenant_id=event_tenant, conversation_id='synthetic-conversation', authenticated_actor_id='operator-1',
                               authenticated_actor_role='sales', source_trace_id='trace-1'),
            requirement=requirement, selected_option=option, replies=[reply],
            gltg_result=SimpleNamespace(gltg_run_id='gltg-run-1', source_api_version='v2'))
    return run, calls


@pytest.mark.parametrize('project_tenant,event_tenant', [('tenant-a', 'tenant-b'), ('', ''), (None, ''), (' ', ' ')])
def test_missing_or_conflicting_tenant_never_calls_gpm(monkeypatch, project_tenant, event_tenant):
    run, calls = invoke(monkeypatch, project_tenant, event_tenant)
    with pytest.raises(GPMGuidanceUnavailableError):
        run()
    assert calls == []


@pytest.mark.parametrize('project_tenant,event_tenant,expected', [
    ('tenant-a', 'tenant-a', 'tenant-a'), ('tenant-a', '', 'tenant-a'),
    (None, 'tenant-a', 'tenant-a'), ('legacy', 'legacy', 'legacy'),
])
def test_known_consistent_tenant_is_preserved_without_inventing_one(monkeypatch, project_tenant, event_tenant, expected):
    run, calls = invoke(monkeypatch, project_tenant, event_tenant)
    run()
    assert len(calls) == 1
    assert calls[0]['tenant_id'] == expected
    assert calls[0]['actor_id'] == 'operator-1'


@pytest.mark.parametrize('project_tenant,event_tenant', [('tenant-a', 'tenant-b'), ('', ''), (None, ''), (' ', ' ')])
def test_invalid_context_stops_before_actual_client_transport(monkeypatch, project_tenant, event_tenant):
    run, requests = invoke(monkeypatch, project_tenant, event_tenant, real_transport=True)
    with pytest.raises(GPMGuidanceUnavailableError) as error:
        run()
    assert 'synthetic downstream body' not in str(error.value)
    assert requests == []
