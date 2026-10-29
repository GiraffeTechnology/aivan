"""Targeted synthetic regressions for revision evidence and ancillary prices."""
from types import SimpleNamespace
import pytest
from aivan.agents import supplier_response_agent as parser
from aivan.api import workbench_routes, attachment_routes  # noqa: F401
from aivan.db.repositories.project_repo import ProjectRepository
from tests.test_inbound_requirement_revision import _revise
from tests.test_invalidated_quote_approval import _approved_quote
from tests.test_rfq_execution_iteration import api_client, api_db  # noqa: F401

@pytest.mark.parametrize('failure', ['context', 'gltg'])
def test_material_revision_keeps_attachment_read_and_export_reference(api_client, api_db, monkeypatch, failure):
    case_id, _, _ = _approved_quote(api_client, monkeypatch)
    project = ProjectRepository(api_db).get(case_id)
    project.requirement_json = {**project.requirement_json, 'giraffe_db_graph': {
        'procurement_case_id': 'synthetic-provider-case', 'rfq_id': 'superseded-rfq'}}
    api_db.commit()
    response = _revise(api_client, monkeypatch, case_id, failure=failure)
    assert response.status_code == 200
    api_db.refresh(project)
    assert not project.requirement_json.get('giraffe_db_graph')
    assert project.selected_option_json is None
    monkeypatch.setattr(attachment_routes, '_get_case', lambda *_: project)
    context = SimpleNamespace(tenant_id=project.tenant_id, trace_id='synthetic-trace')
    seen = []
    def listing(provider_case):
        seen.append(provider_case)
        return [{'attachment_id': 'synthetic-attachment'}]
    def content(attachment_id, provider_case):
        assert attachment_id == 'synthetic-attachment'
        seen.append(provider_case)
        return {'content_type': 'text/plain', 'sha256': 'synthetic-digest'}, b'Saved evidence'
    monkeypatch.setattr(attachment_routes, 'AttachmentClient', lambda *_: SimpleNamespace(list=listing, content=content))
    assert attachment_routes._case_reference(api_db, context, case_id) == 'synthetic-provider-case'
    assert attachment_routes.list_attachments(case_id, api_db, context)['items'][0]['attachment_id'] == 'synthetic-attachment'
    assert attachment_routes.export_attachment_metadata(api_db, context, case_id)[0]['attachment_id'] == 'synthetic-attachment'
    assert attachment_routes.download_attachment(case_id, 'synthetic-attachment', api_db, context).body == b'Saved evidence'
    assert seen == ['synthetic-provider-case'] * 3

@pytest.mark.parametrize('ancillary', ['freight GBP 3.00', 'shipping USD 3.00', 'tooling EUR 100.00', 'sample GBP 20.00', 'packaging GBP 1.00', 'fee GBP 2.00'])
@pytest.mark.parametrize('model_available', [True, False])
def test_ancillary_amount_is_not_an_alternative_unit_price(monkeypatch, ancillary, model_available):
    def model(*_):
        if not model_available:
            raise RuntimeError('synthetic unavailable')
        return {'unit_price': 12.5, 'currency': 'GBP', 'confidence': 0.9}
    monkeypatch.setattr(parser, 'llm_complete_json', model)
    reply = parser.parse_supplier_reply(f'Unit price: GBP 12.50 plus {ancillary}', project_id='synthetic-case')
    assert reply.unit_price == 12.5
    assert reply.currency == 'GBP'
    assert 'unit_price' not in reply.missing_info

@pytest.mark.parametrize('text', ['Unit price GBP 12 or GBP 15 plus freight GBP 3', 'Unit price GBP 12-15 plus shipping USD 3'])
def test_real_unit_price_alternatives_still_require_clarification(monkeypatch, text):
    monkeypatch.setattr(parser, 'llm_complete_json', lambda *_: {'unit_price': 12, 'currency': 'GBP', 'confidence': 0.9})
    reply = parser.parse_supplier_reply(text, project_id='synthetic-case')
    assert reply.unit_price is None
    assert 'unit_price' in reply.missing_info


def test_current_graph_reference_takes_precedence_without_reusing_commercial_fields():
    from aivan.execution.attachment_reference import attachment_provider_case
    project = SimpleNamespace(requirement_json={'attachment_case_reference': {'procurement_case_id': 'old-stable'},
        'giraffe_db_graph': {'procurement_case_id': 'current-stable'}})
    assert attachment_provider_case(project) == 'current-stable'
    project.requirement_json['giraffe_db_graph'] = None
    assert attachment_provider_case(project) == 'old-stable'
    project.requirement_json['attachment_case_reference'] = {'procurement_case_id': None}
    assert attachment_provider_case(project) is None

@pytest.mark.parametrize('text', ['Packaging included, unit price GBP 12.50', 'Sample unit price GBP 12.50', 'Shipping USD 3.00 plus unit price GBP 12.50'])
def test_explicit_unit_price_survives_ancillary_introduction(monkeypatch, text):
    monkeypatch.setattr(parser, 'llm_complete_json', lambda *_: {})
    reply = parser.parse_supplier_reply(text, project_id='synthetic-case')
    assert reply.unit_price == 12.5
    assert reply.currency == 'GBP'
