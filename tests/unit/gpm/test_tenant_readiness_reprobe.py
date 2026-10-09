"""Readiness rechecks authorization using read-only provider contract probes."""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from aivan.gpm.auth import generate_token
from aivan.gpm.giraffe_db_client import GiraffeDBClientError
from aivan.gpm.packet_store import GPMPacketStore
from aivan.gpm import router as router_module


def test_forced_probe_does_not_trust_previous_provider_success(monkeypatch):
    monkeypatch.setenv('AIVAN_ENV', 'production')
    provider = MagicMock()
    store = GPMPacketStore(provider)
    assert store.ensure_tenant_ready('tenant-a')
    provider.check_schema_version.side_effect = GiraffeDBClientError('Synthetic outage', 503)
    assert store.ensure_tenant_ready('tenant-a')  # Existing non-readiness cache compatibility.
    with pytest.raises(HTTPException) as error:
        store.ensure_tenant_ready('tenant-a', force_probe=True)
    assert error.value.status_code == 503
    assert 'tenant-a' not in store._verified_tenants
    with pytest.raises(HTTPException):
        store.ensure_tenant_ready('tenant-a')
    provider.check_schema_version.side_effect = None
    assert store.ensure_tenant_ready('tenant-a', force_probe=True)
    provider.create_packet.assert_not_called()
    provider.update_packet_status.assert_not_called()


def test_provider_removal_invalidates_readiness_cache(monkeypatch):
    monkeypatch.setenv('AIVAN_ENV', 'local')
    store = GPMPacketStore(None)
    store._verified_tenants.add('tenant-a')
    assert store.ensure_tenant_ready('tenant-a', force_probe=True) is False
    assert 'tenant-a' not in store._verified_tenants


@pytest.fixture
def readiness_client(monkeypatch):
    monkeypatch.setenv('AIVAN_ENV', 'production')
    monkeypatch.setenv('AIVAN_AUTH_SECRET', 'synthetic-readiness-signing-secret')
    monkeypatch.setenv('AIVAN_API_KEY', 'synthetic-readiness-deployment-key')
    monkeypatch.setenv('AIVAN_TENANT_ID', 'tenant-a')
    provider = MagicMock()
    provider.get_tenant.return_value = {'status': 'active'}
    store = GPMPacketStore(provider)
    monkeypatch.setattr(router_module, '_packet_store', store)
    app = FastAPI()
    app.state.giraffe_db_client = provider
    app.include_router(router_module.router, prefix='/api/gpm')
    with TestClient(app) as client:
        yield client, provider, store


def headers(tenant='tenant-a'):
    return {'Authorization': 'Bearer ' + generate_token(tenant, 'synthetic-readiness-signing-secret')}


def test_authenticated_route_reprobes_and_never_writes(readiness_client):
    client, provider, store = readiness_client
    first = client.get('/api/gpm/readiness', headers=headers())
    assert first.status_code == 200
    assert first.json() == {'status': 'ok', 'tenant_id': 'tenant-a', 'packet_persistence': 'durable'}
    assert client.get('/api/gpm/readiness', headers=headers()).status_code == 200
    assert provider.check_schema_version.call_count == 2
    assert provider.check_packet_capabilities.call_count == 2
    provider.check_packet_capabilities.side_effect = GiraffeDBClientError('Synthetic permission loss', 403)
    failed = client.get('/api/gpm/readiness', headers=headers())
    assert failed.status_code == 503
    assert failed.json()['detail']['error'] == 'GPM_PERSISTENCE_UNAVAILABLE'
    assert 'tenant-a' not in store._verified_tenants
    provider.create_packet.assert_not_called()
    provider.update_packet_status.assert_not_called()
    provider.create_audit_record.assert_not_called()


def test_route_rejects_auth_and_cross_tenant_before_probe(readiness_client):
    client, provider, store = readiness_client
    assert client.get('/api/gpm/readiness').status_code in (401, 403)
    response = client.get('/api/gpm/readiness', headers={**headers(), 'X-AIVAN-Tenant-ID': 'tenant-b'})
    assert response.status_code == 403
    provider.check_schema_version.assert_not_called()
    provider.check_packet_capabilities.assert_not_called()
    assert store._verified_tenants == set()
