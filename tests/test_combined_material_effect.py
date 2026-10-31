"""A substitute-material time effect is not a total delivery declaration."""
from __future__ import annotations

import pytest

from aivan.agents import supplier_response_agent as parser


@pytest.mark.parametrize("overall", [None, 8.5])
def test_substitute_material_time_effect_remains_separate_from_overall_lead_time(monkeypatch, overall):
    def unavailable(*_args):
        raise RuntimeError("controlled model unavailable")
    monkeypatch.setattr(parser, "llm_complete_json", unavailable)
    text = "Substitute material lead time effect: adds 2 days"
    if overall is not None:
        text = f"Production lead time {overall} days; " + text
    result = parser.parse_supplier_reply(text, "combined-case")
    assert result.lead_time_days == overall
    assert result.material_declarations["fields"]["substitute_lead_time_effect"]["value"] == "adds 2 days"
