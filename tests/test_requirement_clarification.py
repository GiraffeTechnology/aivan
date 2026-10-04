"""Synthetic contract tests; remote dependency acceptance is separate."""
import copy
import pytest
from aivan.execution import requirement_clarification as clarification
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.models.domain import AuditLogRecord
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.integrations.language_skill import apply_to_requirement, source_digest
from aivan.schemas.requirement import BuyerRequirement
from tests.test_myaivan_workbench import workbench, _login, _seed_case


def test_language_overlay_keeps_explicit_domain_evidence_and_source_hash():
    source = 'Synthetic original source'
    req = BuyerRequirement(raw_text=source)
    apply_to_requirement(req, {'normalize': {'canonical_text': 'White cotton shirts', 'field_evidence': {
        'fabric': {'value': 'cotton', 'span': 'original cotton span', 'source': 'language_skill'},
        'color': {'value': 'white', 'span': 'original white span', 'source': 'language_skill'},
    }}, 'structure': {'structured': {'product_name': 'shirt', 'quantity': 100}}})
    assert req.fabric_material == 'cotton'
    assert req.color == 'white'
    assert req.extra['field_sources']['fabric_material'] == 'language_skill'
    assert req.extra['language_skill']['source_text_sha256'] == source_digest(source)
    assert 'span' not in req.extra['field_evidence']['fabric']
    assert req.extra['field_evidence']['fabric']['span_sha256'] == source_digest('original cotton span')


@pytest.fixture
def clarification_case(workbench, monkeypatch):
    client, db = workbench
    session = _login(client)
    project = _seed_case(db, 'buyer-1', 'synthetic-clarification')
    project.requirement_json = BuyerRequirement(product_type='shirt', category='apparel', quantity=100,
        destination='Vancouver', delivery_days=60, fabric_material='cotton', color='white',
        extra={'field_sources': {'product_type': 'language_skill', 'destination': 'language_skill'}}).model_dump()
    project.selected_option_json = {'option_id': 'old-option'}
    project.case_state = 'approved'
    DraftRepository(db).create(project.project_id, {'tenant_id': project.tenant_id, 'message_text': 'Old commercial draft', 'status': 'approved'})
    db.commit()
    calls = []
    def refresh(*args, **kwargs):
        calls.append(kwargs['requirement'].model_dump())
        return {'readback_verified': True, 'procurement_case_id': 'revised-provider-case', 'rfq_id': 'revised-rfq'}, {}, {'p50_days': 30}, kwargs['requirement']
    monkeypatch.setattr(clarification, 'refresh_provider_graph', refresh)
    monkeypatch.setattr(clarification, 'normalize_fields', lambda fields: dict(fields))
    headers = {'X-AIVAN-CSRF': session['csrf_token'], 'Idempotency-Key': 'clarification-1'}
    path = f'/api/workbench/cases/{project.project_id}/requirement'
    digest = client.get(path).json()['requirement_sha256']
    return client, db, project, path, headers, digest, calls


def test_clarification_invalidates_quote_and_is_durable_idempotent(clarification_case):
    client, db, project, path, headers, digest, calls = clarification_case
    body = {'expected_requirement_sha256': digest, 'fields': {'size_ratio': 'S/M/L/XL 20/40/30/10', 'packaging': 'Individually bagged'}}
    response = client.patch(path, headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['approval_invalidated'] is True
    db.expire_all()
    assert project.selected_option_json is None
    assert project.case_state == 'awaiting_supplier'
    assert db.query(InquiryDraftRecord).filter_by(project_id=project.project_id).one().status == 'superseded'
    assert len(calls) == 1
    repeated = client.patch(path, headers=headers, json=body)
    assert repeated.status_code == 200
    assert repeated.json()['replayed'] is True
    assert len(calls) == 1
    record = db.query(AuditLogRecord).filter_by(event_type='REQUIREMENT_CLARIFIED').one()
    assert record.actor_id == 'operator-1' and record.actor_role == 'admin'
    assert client.get(path).json()['requirement']['packaging'] == 'Individually bagged'
    changed = client.patch(path, headers=headers, json={**body, 'fields': {'quantity': 200}})
    assert changed.status_code == 409


@pytest.mark.parametrize('error', ['stale', 'forged_field', 'confirmed', 'provider_failure'])
def test_clarification_fails_without_mutating_state(clarification_case, monkeypatch, error):
    client, db, project, path, headers, digest, calls = clarification_case
    body = {'expected_requirement_sha256': digest, 'fields': {'packaging': 'Bagged'}}
    if error == 'stale': body['expected_requirement_sha256'] = 'a' * 64
    elif error == 'forged_field': body['fields'] = {'order_confirmation': {'status': 'confirmed'}}
    elif error == 'confirmed':
        project.requirement_json = {**project.requirement_json, 'order_confirmation': {'status': 'confirmed'}}
        db.commit()
    else:
        def fail(*args, **kwargs): raise RuntimeError('Synthetic failed provider readback')
        monkeypatch.setattr(clarification, 'refresh_provider_graph', fail)
    response = client.patch(path, headers=headers, json=body)
    assert response.status_code in (409, 422, 503), response.text
    db.expire_all()
    assert project.selected_option_json == {'option_id': 'old-option'}
    assert project.case_state == 'approved'
    assert not db.query(AuditLogRecord).filter_by(event_type='REQUIREMENT_CLARIFIED').all()


def test_clarification_requires_auth_membership_and_allowed_role(clarification_case):
    client, db, project, path, headers, digest, calls = clarification_case
    body = {'expected_requirement_sha256': digest, 'fields': {'packaging': 'Bagged'}}
    assert client.patch(path, json=body).status_code == 403  # CSRF
    session = client.post('/api/session/role', headers={'X-AIVAN-CSRF': headers['X-AIVAN-CSRF']}, json={'role': 'auditor'}).json()
    response = client.patch(path, headers={**headers, 'X-AIVAN-CSRF': session['csrf_token']}, json=body)
    assert response.status_code == 403
    session = client.post('/api/session/role', headers={'X-AIVAN-CSRF': session['csrf_token']}, json={'role': 'buyer'}).json()
    assert client.get(path).status_code == 404  # Buyer is not this case's buyer participant.
    assert calls == []


def test_normalization_is_dynamic_and_fail_closed(monkeypatch):
    from aivan.integrations.language_skill_client import LanguageSkillResult
    class Language:
        def _request(self, method, path, json):
            ok = json['record']['color'] == 'white'
            return LanguageSkillResult(True, {'valid': ok, 'violations': [] if ok else [{'field': 'requirements.color'}]}, None, 200)
        def normalize(self, *, source_text, domain_hint):
            assert source_text == '\u767d\u8272'
            return LanguageSkillResult(True, {'canonical_text': 'white'}, None, 200)
    monkeypatch.setattr(clarification, 'LanguageSkillClient', Language)
    assert clarification.normalize_fields({'color': '\u767d\u8272', 'size_ratio': '20/40/30/10'}) == {'color': 'white', 'size_ratio': '20/40/30/10'}
    class Unavailable(Language):
        def normalize(self, **kwargs): return LanguageSkillResult(False, None, 'unavailable', 503)
    monkeypatch.setattr(clarification, 'LanguageSkillClient', Unavailable)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        clarification.normalize_fields({'color': '\u767d\u8272'})
    assert exc.value.status_code == 503



def test_refresh_executes_existing_gltg_wrapper(workbench, monkeypatch):
    from aivan.domain.roles import normalize_actor_identity
    client, db = workbench
    project = _seed_case(db, 'buyer-1', 'refresh-test')
    requirement = BuyerRequirement(product_type='shirt', category='apparel', quantity=100,
        destination='Vancouver', delivery_days=60, fabric_material='cotton',
        extra={'field_sources': {'product_type': 'operator_confirmed', 'destination': 'operator_confirmed'}})
    monkeypatch.delenv('GIRAFFE_DB_BASE_URL', raising=False)
    monkeypatch.setenv('AIVAN_PERSIST_GIRAFFE_DB_GRAPH', 'false')
    identity = normalize_actor_identity(actor_id='operator-1', business_role='admin', execution_mode='update', authorization_basis='test')
    graph, strategy, gltg, recovered = clarification.refresh_provider_graph(db, project=project,
        requirement=requirement, identity=identity, operation_id='synthetic-refresh')
    assert graph == {}
    assert gltg.get('source_api_version')
    assert recovered == requirement


def test_clarification_provider_reply_loss_recovers_exact_graph(workbench, monkeypatch):
    import httpx
    import json
    from urllib.parse import unquote
    client, db = workbench
    session = _login(client)
    project = _seed_case(db, 'buyer-1', 'provider-clarification')
    project.requirement_json = BuyerRequirement(product_type='shirt', category='apparel', quantity=100,
        destination='Vancouver', delivery_days=60, fabric_material='cotton', color='white',
        extra={'field_sources': {'product_type': 'language_skill', 'destination': 'language_skill'}}).model_dump()
    db.commit()
    monkeypatch.setenv('GIRAFFE_DB_BASE_URL', 'http://synthetic-provider.invalid')
    monkeypatch.setenv('GIRAFFE_DB_SERVICE_AUTH_SECRET', 'synthetic-service-identity')
    monkeypatch.setenv('AIVAN_PERSIST_GIRAFFE_DB_GRAPH', 'true')
    records = {}
    operations = {}
    lost = False
    definitions = {
        '/api/data/buyers': ('buyer_id', 'buyer-1', 'buyers'),
        '/api/data/procurement-cases': ('procurement_case_id', 'case-1', 'procurement_cases'),
        '/api/data/rfqs': ('id', 'rfq-1', 'rfqs'),
        '/api/data/gltg-simulation-runs': ('gltg_run_id', 'gltg-1', 'gltg_runs'),
        '/api/data/pricing-decision-inputs': ('pricing_input_id', 'pricing-1', 'pricing_inputs'),
        '/api/data/case-decision-options': ('decision_option_id', 'option-1', 'decision_options'),
        '/api/data/quote-comparison-snapshots': ('comparison_snapshot_id', 'comparison-1', 'comparison_snapshots'),
    }
    def handle(request):
        nonlocal lost
        assert request.headers['X-Service-Tenant-ID'] == 'test_tenant'
        assert request.headers['X-Service-Auth'] == 'synthetic-service-identity'
        path = request.url.path
        if '/write-results/procurement_cases/' in path:
            key = unquote(path.split('/procurement_cases/')[1])
            record = operations.get(key)
            return httpx.Response(200, json={'status': 'committed', 'record': record}) if record else httpx.Response(404)
        if path.endswith('/transaction-graph'):
            return httpx.Response(200, json={
                'procurement_case': records.get('procurement_cases'),
                **{name: [records[name]] if name in records else [] for name in ('rfqs', 'gltg_runs', 'pricing_inputs', 'decision_options', 'comparison_snapshots')},
            })
        if path == '/api/data/suppliers':
            return httpx.Response(200, json={'total': 0, 'limit': 100, 'offset': 0, 'items': []})
        if request.method == 'POST' and path in definitions:
            key = request.headers['Idempotency-Key']
            field, value, name = definitions[path]
            body = json.loads(request.content)
            record = {**body, field: value, 'tenant_id': 'test_tenant'}
            if key in operations:
                assert operations[key] == record, f'Changed retry payload: {name}'
            else:
                operations[key] = record
                records[name] = record
            if name == 'comparison_snapshots' and not lost:
                lost = True
                raise httpx.ReadTimeout('Synthetic response lost after commit', request=request)
            return httpx.Response(200, json=record)
        return httpx.Response(404)
    real = httpx.Client
    class ProviderClient(real):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault('transport', httpx.MockTransport(handle))
            super().__init__(*args, **kwargs)
    monkeypatch.setattr(httpx, 'Client', ProviderClient)
    path = f'/api/workbench/cases/{project.project_id}/requirement'
    digest = client.get(path).json()['requirement_sha256']
    body = {'expected_requirement_sha256': digest, 'fields': {'packaging': 'Individually bagged', 'size_ratio': '20/40/30/10'}}
    headers = {'X-AIVAN-CSRF': session['csrf_token'], 'Idempotency-Key': 'provider-retry'}
    first = client.patch(path, headers=headers, json=body)
    assert first.status_code == 503, first.text
    assert client.get(path).json()['requirement_sha256'] == digest
    timestamp = records['procurement_cases']['metadata_json']['requirement']['extra']['requirement_clarification']['confirmed_at']
    retry = client.patch(path, headers=headers, json=body)
    assert retry.status_code == 200, retry.text
    assert retry.json()['provider_graph']['readback_verified'] is True
    assert retry.json()['requirement']['extra']['requirement_clarification']['confirmed_at'] == timestamp
    assert len(operations) == 7
    assert records['rfqs']['metadata_json']['requirement'] == records['procurement_cases']['metadata_json']['requirement']


from tests.test_order_confirmation import order_api, _api_headers, OPTION_ID


@pytest.mark.parametrize('field,expected', [('fabric_material', 409), ('size_ratio', 409), ('packaging', 409), ('gsm', 200)])
def test_order_confirmation_blocks_material_gaps_only(order_api, field, expected):
    client, db, case_id, provider = order_api
    from aivan.db.repositories.project_repo import ProjectRepository
    project = ProjectRepository(db).get(case_id, tenant_id='test_tenant')
    project.requirement_json = {**project.requirement_json, 'missing_fields': [{'field_name': field}]}
    db.commit()
    response = client.post(f'/api/workbench/cases/{case_id}/order-confirmation',
        headers=_api_headers(), json={'selected_option_id': OPTION_ID})
    assert response.status_code == expected, response.text
    if expected == 409:
        assert provider.post_calls == []


def test_normalization_digest_survives_raw_omission(monkeypatch):
    from aivan.integrations.language_skill import canonicalize_rfq
    from aivan.integrations.language_skill_client import LanguageSkillResult
    class SyntheticLanguage:
        def normalize(self, **kwargs):
            return LanguageSkillResult(True, {'canonical_text': 'A canonical English shirt inquiry'}, None, 200)
        def structure_rfq(self, **kwargs):
            return LanguageSkillResult(True, {'structured': {'product_name': 'shirt'}}, None, 200)
    monkeypatch.setenv('AIVAN_LANGUAGE_SKILL_ENABLED', 'true')
    original = 'The original synthetic inquiry wording'
    canon = canonicalize_rfq(original, client=SyntheticLanguage())
    req = BuyerRequirement(raw_text=canon['normalize']['canonical_text'])
    apply_to_requirement(req, canon)
    assert req.extra['language_skill']['source_text_sha256'] == source_digest(original)
