"""Synthetic response-mutation probes; not evidence of a real provider defect."""
from copy import deepcopy

import httpx
import pytest

from aivan.integrations.order_confirmation import OrderConfirmationError
from tests.test_order_confirmation import (
    CASE_ID, RFQ_ID, ProviderContractFixture, _client, _identity, _option,
)


@pytest.mark.parametrize('mismatch', [
    'graph-case', 'quote-case', 'order-case', 'quote-rfq', 'order-supplier',
    'graph-order-selection', 'graph-quote-supplier', 'quote-tenant',
])
def test_reconcile_does_not_verify_contradictory_readback(monkeypatch, mismatch):
    fixture = ProviderContractFixture()
    client = _client(monkeypatch, fixture)
    first = client.confirm_order(project_id='project-1',
        graph_reference={'procurement_case_id': CASE_ID, 'rfq_id': RFQ_ID},
        selected_option=_option(), identity=_identity(), request_key='first-request')
    post_count = len(fixture.post_calls)

    def mutate(request):
        response = fixture(request)
        data = deepcopy(response.json())
        if request.url.path.endswith('/transaction-graph'):
            if mismatch == 'graph-case':
                data['procurement_case']['procurement_case_id'] = 'other-case'
            if mismatch == 'graph-order-selection':
                data['purchase_orders'][0]['selected_quote_id'] = 'other-quote'
            if mismatch == 'graph-quote-supplier':
                data['supplier_quotes'][0]['supplier_id'] = 'other-supplier'
        elif '/supplier-quotes/' in request.url.path:
            if mismatch == 'quote-case': data['procurement_case_id'] = 'other-case'
            if mismatch == 'quote-rfq': data['rfq_id'] = 'other-rfq'
            if mismatch == 'quote-tenant': data['tenant_id'] = 'other-tenant'
        elif '/purchase-orders/' in request.url.path:
            if mismatch == 'order-case': data['procurement_case_id'] = 'other-case'
            if mismatch == 'order-supplier': data['supplier_id'] = 'other-supplier'
        return httpx.Response(response.status_code, json=data)

    client._transport = httpx.MockTransport(mutate)
    with pytest.raises(OrderConfirmationError):
        client.reconcile_order(procurement_case_id=CASE_ID,
            supplier_quote_id=first.supplier_quote_id, purchase_order_id=first.purchase_order_id)
    assert len(fixture.post_calls) == post_count

def test_compatible_provider_may_omit_optional_identity_echoes(monkeypatch):
    fixture = ProviderContractFixture()
    client = _client(monkeypatch, fixture)
    result = client.confirm_order(project_id='project-1',
        graph_reference={'procurement_case_id': CASE_ID, 'rfq_id': RFQ_ID},
        selected_option=_option(), identity=_identity(), request_key='compatible-request')

    def minimal(request):
        response = fixture(request)
        data = deepcopy(response.json())
        if '/supplier-quotes/' in request.url.path:
            data = {key: data[key] for key in ('quote_id', 'supplier_id')}
        elif '/purchase-orders/' in request.url.path:
            data = {key: data[key] for key in ('po_id', 'rfq_id', 'selected_quote_id', 'status')}
        elif request.url.path.endswith('/transaction-graph'):
            data['supplier_quotes'] = [{'quote_id': result.supplier_quote_id}]
            data['purchase_orders'] = [{'po_id': result.purchase_order_id}]
        return httpx.Response(200, json=data)

    client._transport = httpx.MockTransport(minimal)
    recovered = client.reconcile_order(procurement_case_id=CASE_ID,
        supplier_quote_id=result.supplier_quote_id, purchase_order_id=result.purchase_order_id)
    assert recovered.readback_verified is True
    assert recovered.rfq_id == RFQ_ID
