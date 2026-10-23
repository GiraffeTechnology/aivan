"""New A09 reproduction; consumer HTTP fixture, not real-provider evidence."""
from __future__ import annotations

import httpx
import pytest

from aivan.schemas.rfq import RFQStrategy
from tests import test_graph_readback_lineage as fixture_module
from tests.test_graph_readback_lineage import invoke_graph  # noqa: F401


@pytest.mark.parametrize(('scope', 'label'), [
    ('known_suppliers_only', 'The selected sourcing strategy is to use only known suppliers.'),
    ('known_suppliers_first', 'The selected sourcing strategy is to prioritize known suppliers.'),
    ('public_bidding_first', 'The selected sourcing strategy is to prioritize public bidding.'),
    ('parallel_known_and_public', 'The selected sourcing strategy evaluates known suppliers and public bidding in parallel.'),
])
def test_saved_decision_label_matches_actual_supplier_strategy(invoke_graph, monkeypatch, scope, label):
    _, _, invoke = invoke_graph
    monkeypatch.setattr(fixture_module, 'RFQStrategy', lambda: RFQStrategy(supplier_scope=scope))
    saved = []
    original_post = httpx.Client.post

    def capture(client, url, *args, **kwargs):
        if url.endswith('/api/data/case-decision-options'):
            saved.append(kwargs['json'])
        return original_post(client, url, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, 'post', capture)
    assert invoke()['readback_verified'] is True
    assert len(saved) == 1
    assert saved[0]['option_type'] == scope
    # The type is the machine enum; its display label preserves the exact
    # canonical English strategy meaning, not a duplicate machine identifier.
    assert saved[0]['option_label'] == label


@pytest.mark.parametrize('scope', [
    'known_suppliers_only', 'known_suppliers_first',
    'public_bidding_first', 'parallel_known_and_public',
])
def test_prequote_graph_does_not_invent_a_recommendation_score(invoke_graph, monkeypatch, scope):
    _, _, invoke = invoke_graph
    monkeypatch.setattr(fixture_module, 'RFQStrategy', lambda: RFQStrategy(supplier_scope=scope))
    saved = []
    original_post = httpx.Client.post

    def capture(client, url, *args, **kwargs):
        if url.endswith('/api/data/case-decision-options'):
            saved.append(kwargs['json'])
        return original_post(client, url, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, 'post', capture)
    assert invoke()['readback_verified'] is True
    assert len(saved) == 1
    # This pre-quotation path has no scored candidate input. The selected
    # provider's recommendation_score is nullable, so unknown stays unknown.
    assert saved[0].get('recommendation_score') is None
