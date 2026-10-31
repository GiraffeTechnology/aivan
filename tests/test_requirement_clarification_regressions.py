"""Regression coverage for PR 138. Provider transports remain synthetic.

Set AIVAN_REGRESSION_MYSQL_URL to a disposable MySQL database to exercise
real SQL persistence through the same authenticated API flows.
"""
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from aivan.db.models import Base
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.execution import requirement_clarification as clarification
from aivan.execution.safety import evaluate_requirement_readiness
from aivan.schemas.requirement import BuyerRequirement
from tests import test_myaivan_workbench as workbench_module
from tests import test_order_confirmation as order_module
from tests.test_requirement_clarification import clarification_case
from tests.test_myaivan_workbench import workbench
from tests.test_order_confirmation import order_api, _api_headers, OPTION_ID


@pytest.fixture(autouse=True)
def optional_mysql_backend(monkeypatch):
    """Only the explicitly supplied disposable database may be recreated."""
    url = os.environ.get('AIVAN_REGRESSION_MYSQL_URL')
    if not url:
        yield
        return
    target = make_url(url)
    assert target.drivername == 'mysql+pymysql', 'A real MySQL test URL is required'
    assert target.host in {'127.0.0.1', 'localhost'}, 'Only the local disposable server is allowed'
    assert target.database == 'aivan_r15_test', 'Only the disposable regression schema is allowed'
    engine = create_engine(url)
    assert engine.dialect.name == 'mysql'
    with engine.connect() as connection:
        version = connection.exec_driver_sql('SELECT VERSION()').scalar_one()
        assert version.startswith('8.'), version
    Base.metadata.drop_all(engine)
    monkeypatch.setattr(workbench_module, 'create_engine', lambda *a, **kw: engine)
    monkeypatch.setattr(order_module, 'create_engine', lambda *a, **kw: engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_partial_correction_persists_before_provider_readiness(clarification_case, monkeypatch):
    client, db, project, path, headers, digest, calls = clarification_case
    project.requirement_json = {**project.requirement_json, 'destination': '', 'delivery_days': None}
    db.commit()
    digest = client.get(path).json()['requirement_sha256']
    original_refresh = clarification.refresh_provider_graph
    def guarded_refresh(*args, **kwargs):
        gate = evaluate_requirement_readiness(kwargs['requirement'])
        if not gate.ready:
            raise HTTPException(409, detail={'error': 'REQUIREMENT_CORE_CLARIFICATION_REQUIRED'})
        return original_refresh(*args, **kwargs)
    monkeypatch.setattr(clarification, 'refresh_provider_graph', guarded_refresh)
    body = {'expected_requirement_sha256': digest, 'fields': {'destination': 'Vancouver'}}
    first = client.patch(path, headers=headers, json=body)
    assert first.status_code == 200, first.text
    db.expire_all()
    persisted = client.get(path).json()
    assert persisted['requirement']['destination'] == 'Vancouver'
    assert 'delivery_days' in {f['field_name'] for f in persisted['requirement']['missing_fields']}
    assert project.case_state == 'inquiry'
    assert calls == []
    replay = client.patch(path, headers=headers, json=body)
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    second = client.patch(path, headers={**headers, 'Idempotency-Key': 'clarification-2'}, json={
        'expected_requirement_sha256': persisted['requirement_sha256'], 'fields': {'delivery_days': 60}})
    assert second.status_code == 200, second.text
    assert len(calls) == 1
    assert project.case_state == 'awaiting_supplier'


@pytest.mark.parametrize('quantity', ['100', '100.0', 100, 100.0])
def test_equivalent_validated_quantity_preserves_approval(clarification_case, quantity):
    client, db, project, path, headers, digest, calls = clarification_case
    response = client.patch(path, headers=headers, json={
        'expected_requirement_sha256': digest, 'fields': {'quantity': quantity}})
    assert response.status_code == 200, response.text
    assert response.json()['changed_fields'] == []
    assert response.json()['approval_invalidated'] is False
    db.expire_all()
    assert project.selected_option_json == {'option_id': 'old-option'}
    assert project.case_state == 'approved'
    assert db.query(InquiryDraftRecord).filter_by(project_id=project.project_id).one().status == 'approved'


@pytest.mark.parametrize('field', ['material_spec', 'tolerance', 'surface_finish', 'process_type'])
def test_cnc_fields_can_be_corrected(clarification_case, field):
    client, db, project, path, headers, digest, calls = clarification_case
    project.requirement_json = {**project.requirement_json, 'category': 'cnc',
        'material_spec': 'Aluminum 6061', 'tolerance': '0.1 mm'}
    db.commit()
    digest = client.get(path).json()['requirement_sha256']
    response = client.patch(path, headers=headers, json={
        'expected_requirement_sha256': digest, 'fields': {field: 'Operator confirmed specification'}})
    assert response.status_code == 200, response.text
    assert response.json()['approval_invalidated'] is True
    db.expire_all()
    assert client.get(path).json()['requirement'][field] == 'Operator confirmed specification'


@pytest.mark.parametrize('field', ['material_spec', 'tolerance'])
def test_cnc_material_gaps_block_order_confirmation(order_api, field):
    client, db, case_id, provider = order_api
    from aivan.db.repositories.project_repo import ProjectRepository
    project = ProjectRepository(db).get(case_id, tenant_id='test_tenant')
    project.requirement_json = {**project.requirement_json, 'category': 'cnc',
        'missing_fields': [{'field_name': field}]}
    db.commit()
    response = client.post(f'/api/workbench/cases/{case_id}/order-confirmation',
        headers=_api_headers(), json={'selected_option_id': OPTION_ID})
    assert response.status_code == 409, response.text
    assert provider.post_calls == []
