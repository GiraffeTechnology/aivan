"""Synthetic graph consumer checks; not real provider/MySQL acceptance."""
from copy import deepcopy

import httpx
import pytest

from tests.test_graph_readback_lineage import invoke_graph  # noqa: F401

RELATIONS = {
    "procurement_case": {"buyer_id": "b1"},
    "rfqs": {"buyer_id": "b1", "procurement_case_id": "pc1"},
    "gltg_runs": {"buyer_id": "b1", "procurement_case_id": "pc1", "rfq_id": "rfq1"},
    "pricing_inputs": {
        "buyer_id": "b1", "procurement_case_id": "pc1", "rfq_id": "rfq1", "gltg_run_id": "g1",
    },
    "decision_options": {"buyer_id": "b1", "procurement_case_id": "pc1", "rfq_id": "rfq1"},
    "comparison_snapshots": {"buyer_id": "b1", "procurement_case_id": "pc1", "rfq_id": "rfq1"},
}
WRITE_PATHS = {
    "procurement_case": ("procurement-case", "/api/data/procurement-cases"),
    "rfqs": ("rfq", "/api/data/rfqs"),
    "gltg_runs": ("gltg-run", "/api/data/gltg-simulation-runs"),
    "pricing_inputs": ("pricing-input", "/api/data/pricing-decision-inputs"),
    "decision_options": ("decision-option", "/api/data/case-decision-options"),
    "comparison_snapshots": ("comparison-snapshot", "/api/data/quote-comparison-snapshots"),
}
LINKS = [(section, field) for section, fields in RELATIONS.items() for field in fields]


@pytest.mark.parametrize("section,field", LINKS)
@pytest.mark.parametrize("wrong_link", [None, "unrelated-business-record"])
def test_graph_readback_rejects_contradictory_relation(invoke_graph, section, field, wrong_link):
    graph, calls, invoke = invoke_graph
    record = graph[section] if section == "procurement_case" else graph[section][0]
    record[field] = wrong_link
    with pytest.raises(RuntimeError, match=f"GIRAFFE_DB_GRAPH_READBACK_RELATION_MISMATCH:{section}:{field}"):
        invoke()
    # Existing writes precede readback; rejection is not rollback or zero writes.
    assert len([method for method, _ in calls if method == "POST"]) == 7
    assert calls[-1] == ("GET", "/api/data/procurement-cases/pc1/transaction-graph")


@pytest.mark.parametrize("section,field", LINKS)
def test_graph_write_rejects_contradictory_relation_before_later_operations(
    invoke_graph, monkeypatch, section, field,
):
    _, calls, invoke = invoke_graph
    step, path = WRITE_PATHS[section]
    original = httpx.Client.post

    def post(client, url, *args, **kwargs):
        response = original(client, url, *args, **kwargs)
        if url.endswith(path):
            return httpx.Response(201, request=response.request,
                json={**response.json(), field: "unrelated-business-record"})
        return response

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(RuntimeError, match=f"GIRAFFE_DB_GRAPH_RESPONSE_RELATION_MISMATCH:{step}:{field}"):
        invoke()
    assert len(calls) == list(WRITE_PATHS).index(section) + 2
    assert all(method == "POST" for method, _ in calls)
    assert calls[-1] == ("POST", path)


def test_graph_readback_matching_relation_echoes(invoke_graph):
    graph, _, invoke = invoke_graph
    for section, fields in RELATIONS.items():
        record = graph[section] if section == "procurement_case" else graph[section][0]
        record.update(fields)
    assert invoke()["readback_verified"] is True


def test_graph_readback_omitted_relation_echo_remains_compatible(invoke_graph):
    _, _, invoke = invoke_graph
    assert invoke()["readback_verified"] is True


def test_graph_write_matching_relation_echoes(invoke_graph, monkeypatch):
    _, _, invoke = invoke_graph
    original = httpx.Client.post
    fields = {field for values in RELATIONS.values() for field in values}

    def post(client, url, *args, **kwargs):
        response = original(client, url, *args, **kwargs)
        echo = {field: value for field, value in kwargs["json"].items() if field in fields}
        return httpx.Response(201, request=response.request, json={**response.json(), **echo})

    monkeypatch.setattr(httpx.Client, "post", post)
    assert invoke()["readback_verified"] is True


def test_graph_unrelated_history_does_not_supply_relation_evidence(invoke_graph):
    graph, _, invoke = invoke_graph
    historical = deepcopy(graph["gltg_runs"][0])
    historical.update(gltg_run_id="unrelated-historical-run", procurement_case_id="other-case")
    graph["gltg_runs"].insert(0, historical)
    assert invoke()["readback_verified"] is True


def test_graph_duplicate_selected_id_cannot_hide_wrong_relation(invoke_graph):
    graph, _, invoke = invoke_graph
    record = graph["gltg_runs"][0]
    record["procurement_case_id"] = "pc1"
    contradictory = deepcopy(record)
    contradictory["procurement_case_id"] = "other-case"
    graph["gltg_runs"].append(contradictory)
    with pytest.raises(RuntimeError, match="GIRAFFE_DB_GRAPH_READBACK_RELATION_MISMATCH:gltg_runs:procurement_case_id"):
        invoke()
