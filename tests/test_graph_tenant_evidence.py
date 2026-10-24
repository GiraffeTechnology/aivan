"""Synthetic consumer regressions, not real-provider/MySQL acceptance evidence."""
from __future__ import annotations

import httpx
import pytest

from tests.test_graph_readback_lineage import invoke_graph  # noqa: F401

SECTIONS = (
    "procurement_case", "rfqs", "gltg_runs", "pricing_inputs",
    "decision_options", "comparison_snapshots",
)
WRITE_STEPS = (
    ("buyer", "/api/data/buyers"),
    ("procurement-case", "/api/data/procurement-cases"),
    ("rfq", "/api/data/rfqs"),
    ("gltg-run", "/api/data/gltg-simulation-runs"),
    ("pricing-input", "/api/data/pricing-decision-inputs"),
    ("decision-option", "/api/data/case-decision-options"),
    ("comparison-snapshot", "/api/data/quote-comparison-snapshots"),
)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("wrong_tenant", ["other-tenant", "", None])
def test_graph_readback_rejects_explicit_wrong_tenant(invoke_graph, section, wrong_tenant):
    graph, calls, invoke = invoke_graph
    record = graph[section] if section == "procurement_case" else graph[section][0]
    record["tenant_id"] = wrong_tenant

    with pytest.raises(RuntimeError, match=f"GIRAFFE_DB_GRAPH_READBACK_TENANT_MISMATCH:{section}"):
        invoke()
    # Writes have already happened; this is not a rollback or zero-write claim.
    assert len([method for method, _ in calls if method == "POST"]) == 7
    assert calls[-1] == ("GET", "/api/data/procurement-cases/pc1/transaction-graph")


@pytest.mark.parametrize("index,step,path", [(i, *item) for i, item in enumerate(WRITE_STEPS)])
def test_graph_write_rejects_wrong_tenant_before_dependent_operations(
    invoke_graph, monkeypatch, index, step, path,
):
    _, calls, invoke = invoke_graph
    original_post = httpx.Client.post

    def post(client, url, *args, **kwargs):
        response = original_post(client, url, *args, **kwargs)
        if url.endswith(path):
            return httpx.Response(201, json={**response.json(), "tenant_id": "other-tenant"})
        return response

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(RuntimeError, match=f"GIRAFFE_DB_GRAPH_RESPONSE_TENANT_MISMATCH:{step}"):
        invoke()
    assert len(calls) == index + 1
    assert all(method == "POST" for method, _ in calls)
    # The ambiguous write itself may have committed; no later operation runs.
    assert calls[-1] == ("POST", path)


@pytest.mark.parametrize("echo_tenant", [False, True])
def test_graph_accepts_matching_or_omitted_tenant_echo(invoke_graph, echo_tenant):
    graph, _, invoke = invoke_graph
    if echo_tenant:
        for section in SECTIONS:
            records = [graph[section]] if section == "procurement_case" else graph[section]
            for record in records:
                record["tenant_id"] = "tenant-graph-unit"
    assert invoke()["readback_verified"] is True


def test_graph_does_not_use_an_unrelated_historical_tenant(invoke_graph):
    from copy import deepcopy

    graph, _, invoke = invoke_graph
    historical = deepcopy(graph["gltg_runs"][0])
    historical.update(gltg_run_id="unrelated-old-run", tenant_id="other-tenant")
    graph["gltg_runs"].insert(0, historical)
    # Only the selected record is readback evidence for this write.
    assert invoke()["readback_verified"] is True
