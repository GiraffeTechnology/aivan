"""Execution-read boundary unit cases; synthetic HTTP/SQLite, not live E2E."""
import base64
import json
from dataclasses import replace

import httpx
import pytest

from aivan.api.request_context import RequestContext

TENANT = 'test_tenant'
LOCAL_TENANT = '11111111-1111-4111-8111-111111111111'
OPERATOR = '22222222-2222-4222-8222-222222222222'
ORDER = '33333333-3333-4333-8333-333333333333'
PROJECT = '44444444-4444-4444-8444-444444444444'
SHIPMENT = '55555555-5555-4555-8555-555555555555'
PRIVATE_KEY = 'synthetic-private-key-for-tests-0123456789'


def context():
    return RequestContext(TENANT, 'trace-fixture', '', 'installation-operator', 'admin', '',
                          'audit', '', '', '', '', 'ui_session', True)


def association():
    return {'schema_version': 'aivan.execution-association.v1', 'case_id': 'case-fixture',
            'status': 'associated', 'readback_verified': True, 'execution_reads_available': False,
            'local_order_id': ORDER, 'local_project_id': PROJECT}


@pytest.fixture
def profile(monkeypatch):
    monkeypatch.setenv('MYAIVAN_EXECUTION_BASE_URL', 'http://127.0.0.1:18767')
    monkeypatch.setenv('MYAIVAN_EXECUTION_WEB_ACTOR_ID', 'installation-operator')
    monkeypatch.setenv('AIVAN_UI_ACTOR_ID', 'installation-operator')
    monkeypatch.setenv('MYAIVAN_FULFILLMENT_TENANTS', json.dumps({TENANT: {
        'tenant_id': LOCAL_TENANT, 'operator_id': OPERATOR}}))
    monkeypatch.setenv('MYAIVAN_FULFILLMENT_API_KEYS', json.dumps({TENANT: PRIVATE_KEY}))


def token(actor=OPERATOR):
    payload = base64.urlsafe_b64encode(json.dumps({'sub': actor}).encode()).decode().rstrip('=')
    return 'synthetic.' + payload + '.signature'


def transport(calls, *, resource_status=200, session_tenant=LOCAL_TENANT, actor=OPERATOR,
              order_project=PROJECT, shipment_order=ORDER):
    def handle(request):
        calls.append(request)
        if request.url.path == '/api/installation/session':
            assert request.method == 'POST'
            assert request.headers['X-AIVAN-Tenant-ID'] == TENANT
            assert request.headers['X-AIVAN-API-Key'] == PRIVATE_KEY
            return httpx.Response(200, json={'access_token': token(actor), 'token_type': 'bearer',
                                            'tenant_id': session_tenant, 'provider_tenant_id': TENANT})
        assert request.method == 'GET'
        assert request.headers['Authorization'] == 'Bearer ' + token(actor)
        assert 'X-AIVAN-API-Key' not in request.headers
        if request.url.path == f'/api/orders/{ORDER}':
            return httpx.Response(200, json={'id': ORDER, 'project_id': order_project, 'status': 'CONFIRMED'})
        data = ({'id': SHIPMENT, 'order_id': shipment_order} if '/shipments/' in request.url.path
                else [] if request.url.path.endswith(('qc-records', ORDER))
                else {'milestones': [], 'monitoring_packet': None})
        return httpx.Response(resource_status, json=data if resource_status == 200 else {'secret': 'never-echo-upstream'},
                              headers={'Set-Cookie': 'never-forward', 'Location': 'https://invalid.example'})
    return httpx.MockTransport(handle)


@pytest.mark.parametrize('resource,path', [('order', f'/api/orders/{ORDER}'),
    ('production', f'/api/orders/{ORDER}/production-monitoring'),
    ('qc', f'/api/orders/{ORDER}/qc-records'), ('events', f'/api/execution-graph/orders/{ORDER}'),
    ('shipment', f'/api/shipments/{SHIPMENT}')])
def test_selected_resource_uses_existing_operator_bridge_and_bound_order(profile, resource, path):
    from aivan.integrations.execution_read import ExecutionReadClient
    calls = []
    client = ExecutionReadClient(context(), transport=transport(calls))
    result = client.read(association(), resource, shipment_id=SHIPMENT if resource == 'shipment' else None)
    assert result.status_code == 200
    assert calls[-1].url.path == path
    assert sum(r.method == 'POST' for r in calls) == 1
    assert all(r.method == 'GET' or r.url.path == '/api/installation/session' for r in calls)


@pytest.mark.parametrize('change', [{'actor_id': 'arbitrary-admin'}, {'role_context': 'auditor'},
    {'role_context': 'buyer'}, {'authorization_basis': 'ui_test_session'},
    {'authorization_basis': 'tenant_api_key'}, {'tenant_id': 'foreign-tenant'}])
def test_unmapped_web_identity_rejected_before_network(profile, change):
    from aivan.integrations.execution_read import ExecutionReadClient, ExecutionReadError
    calls = []
    with pytest.raises(ExecutionReadError):
        ExecutionReadClient(replace(context(), **change), transport=transport(calls)).read(association(), 'order')
    assert calls == []


@pytest.mark.parametrize('change', [{'status': 'unavailable'}, {'readback_verified': False},
    {'local_order_id': '..'}, {'local_order_id': 'po-fixture'}, {'local_project_id': PROJECT + '%2f..'}])
def test_invalid_or_unverified_association_never_issues_session(profile, change):
    from aivan.integrations.execution_read import ExecutionReadClient, ExecutionReadError
    calls = []
    with pytest.raises(ExecutionReadError):
        ExecutionReadClient(context(), transport=transport(calls)).read({**association(), **change}, 'order')
    assert calls == []


@pytest.mark.parametrize('status', [201, 204, 302, 401, 403, 404, 409, 429, 503])
def test_exact_http_outcomes_fail_without_redirect_or_raw_error(profile, status):
    from aivan.integrations.execution_read import ExecutionReadClient, ExecutionReadError
    calls = []
    with pytest.raises(ExecutionReadError) as caught:
        ExecutionReadClient(context(), transport=transport(calls, resource_status=status)).read(association(), 'qc')
    assert 'never-echo-upstream' not in str(caught.value)
    assert caught.value.status == (status if status in {401, 403, 404, 409, 429, 503} else 502)
    assert len(calls) == 3


@pytest.mark.parametrize('kwargs', [{'session_tenant': PROJECT}, {'actor': PROJECT},
    {'order_project': OPERATOR}, {'shipment_order': PROJECT}])
def test_cross_identity_results_fail_closed(profile, kwargs):
    from aivan.integrations.execution_read import ExecutionReadClient, ExecutionReadError
    calls = []
    with pytest.raises(ExecutionReadError):
        ExecutionReadClient(context(), transport=transport(calls, **kwargs)).read(association(), 'shipment', shipment_id=SHIPMENT)


@pytest.mark.parametrize('path', ['/api/workbench/cases/missing/execution/order',
                                '/api/workbench/cases/missing/execution/qc'])
def test_real_app_routes_require_auth_before_upstream(workbench, path):
    # Import the existing SQLite ASGI fixture, not a substitute target server.
    client, _ = workbench
    assert client.get(path).status_code == 401


from tests.test_myaivan_workbench import workbench  # noqa: E402,F401


@pytest.mark.parametrize('role,actor,expected', [('admin', 'installation-operator', 200),
    ('buyer', 'installation-operator', 403), ('auditor', 'installation-operator', 403),
    ('admin', 'arbitrary-admin', 403)])
def test_signed_session_route_preserves_actor_mapping_and_provider_binding(workbench, profile, monkeypatch, role, actor, expected):
    from aivan.api import execution_association_routes
    from aivan.integrations import execution_read
    from tests.test_myaivan_workbench import _seed_case, _login
    client, db = workbench
    monkeypatch.setenv('AIVAN_UI_ACTOR_ID', actor)
    case = _seed_case(db, actor, 'execution-signed-session')
    state = {'schema_version': 'abcdYi.execution.v1', 'source_po_id': 'po-fixture',
             'source_quote_id': 'quote-fixture', 'source_snapshot_hash': 'a' * 64,
             'local_order_id': ORDER, 'local_project_id': PROJECT}
    order = {'tenant_id': TENANT, 'po_id': 'po-fixture', 'procurement_case_id': 'case-ref',
             'rfq_id': 'rfq-fixture', 'selected_quote_id': 'quote-fixture', 'status': 'confirmed',
             'source_snapshot_hash': 'a' * 64, 'execution_revision': 1,
             'metadata_json': {'aivan_project_id': case.project_id, 'abcdyi_execution': state}}
    envelope = {'tenant_id': TENANT, 'po_id': 'po-fixture', 'revision': 1,
                'source_snapshot_hash': 'a' * 64, 'state': state}
    confirmation = {'status': 'confirmed', 'purchase_order_id': 'po-fixture',
                    'supplier_quote_id': 'quote-fixture', 'procurement_case_id': 'case-ref', 'rfq_id': 'rfq-fixture'}
    graph = {'procurement_case_id': 'case-ref', 'rfq_id': 'rfq-fixture'}
    case.requirement_json = {'order_confirmation': confirmation, 'giraffe_db_graph': graph}
    db.commit()
    order['tenant_id'], envelope['tenant_id'] = TENANT, TENANT
    order['metadata_json']['aivan_project_id'] = case.project_id
    state = envelope['state']
    state.update(local_order_id=ORDER, local_project_id=PROJECT)
    order['metadata_json']['abcdyi_execution'] = state
    provider_calls, requests = [], []
    class Provider:
        tenant_id = TENANT
        def __init__(self, **kwargs):
            assert kwargs['tenant_id'] == TENANT
        def _request(self, method, path):
            provider_calls.append((method, path))
            assert method == 'GET'
            return httpx.Response(200, json=envelope if path.endswith('/execution-state') else order)
    monkeypatch.setattr(execution_association_routes, 'GiraffeDBOrderConfirmationClient', Provider)
    monkeypatch.setattr(execution_read, '_DEFAULT_TRANSPORT', transport(requests))
    login = _login(client)
    if role != 'admin':
        switched = client.post('/api/session/role', headers={'X-AIVAN-CSRF': login['csrf_token']}, json={'role': role})
        assert switched.status_code == 200
    response = client.get(f'/api/workbench/cases/{case.project_id}/execution/order')
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json()['id'] == ORDER
        assert len(provider_calls) == 3 and len(requests) == 2
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'Set-Cookie' not in response.headers
        assert PRIVATE_KEY not in response.text and token() not in response.text
        association_response = client.get(f'/api/workbench/cases/{case.project_id}/execution-association')
        assert association_response.status_code == 200
        assert association_response.json()['execution_reads_available'] is True
        assert association_response.json()['execution_readiness'] == 'not_checked'
        assert association_response.json()['execution_read_prefix'] == f'/api/workbench/cases/{case.project_id}/execution'
        assert len(requests) == 2  # Advertising the route does not probe/mint a token.
    else:
        assert provider_calls == [] and requests == []


def test_runtime_propagates_real_allocated_execution_endpoint(tmp_path, monkeypatch):
    from tests.test_myaivan_installer import m
    root, release = tmp_path / 'prefix', tmp_path / 'release'
    root.mkdir(); release.mkdir()
    (release / 'manifest.json').write_text(json.dumps({'components': {'aivan': {'revision': 'a' * 40}}}))
    config = m.new_config(['tenant-fixture'])
    config.update(database_mode='isolated', host_profile='isolated')
    config['ports'] = {name: 18000 + index for index, name in enumerate(m.SERVICES)}
    env = m.environment(root, release, config)
    assert env['MYAIVAN_EXECUTION_BASE_URL'] == f"http://127.0.0.1:{config['ports']['abcdyi']}"
    assert env['MYAIVAN_EXECUTION_WEB_ACTOR_ID'] == env['AIVAN_UI_ACTOR_ID'] == 'installation-operator'
    assert json.loads(env['MYAIVAN_FULFILLMENT_TENANTS']) == config['fulfillment']['tenants']


@pytest.mark.parametrize('resource,shipment', [('https://invalid.example', None),
    ('shipment', '..'), ('shipment', SHIPMENT + '%2fother')])
def test_non_allowlisted_paths_never_call_upstream(profile, resource, shipment):
    from aivan.integrations.execution_read import ExecutionReadClient, ExecutionReadError
    calls = []
    with pytest.raises(ExecutionReadError):
        ExecutionReadClient(context(), transport=transport(calls)).read(association(), resource, shipment_id=shipment)
    assert calls == []


def test_foreign_case_is_hidden_before_execution_client_construction(workbench, profile, monkeypatch):
    from aivan.api import execution_read_routes
    from tests.test_myaivan_workbench import _seed_case, _login
    client, db = workbench
    case = _seed_case(db, 'installation-operator', 'foreign-execution-case')
    case.tenant_id = 'foreign-tenant'
    db.commit()
    def forbidden(*args, **kwargs):
        pytest.fail('Case ACL must run before constructing the execution client')
    monkeypatch.setattr(execution_read_routes, 'ExecutionReadClient', forbidden)
    _login(client)
    response = client.get(f'/api/workbench/cases/{case.project_id}/execution/order')
    assert response.status_code == 404


def test_api_key_header_cannot_claim_installer_operator(workbench, profile):
    client, db = workbench
    from tests.test_myaivan_workbench import _seed_case
    case = _seed_case(db, 'installation-operator', 'api-key-execution-case')
    response = client.get(f'/api/workbench/cases/{case.project_id}/execution/order', headers={
        'X-AIVAN-API-Key': 'test-deployment-key', 'X-AIVAN-Actor-ID': 'installation-operator',
        'X-AIVAN-Role-Context': 'admin'})
    assert response.status_code == 403
    assert response.json()['detail']['error'] == 'EXECUTION_READ_FORBIDDEN'
