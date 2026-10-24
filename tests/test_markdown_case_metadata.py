"""Pure actual-DTO Markdown export tests; no DB/API/network acceptance claim."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from aivan.api.workbench_routes import _case_summary, _markdown_export


def case_payload():
    project = SimpleNamespace(
        project_id="synthetic-export-case", status="active", case_state="inquiry",
        category="apparel", customer_id="synthetic-buyer", customer_display_name="Buyer",
        channel="myaivan", source_trace_id="synthetic-trace",
        requirement_json={"product_name": "Synthetic cotton shirt inquiry"},
        created_at=datetime(2001, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
        updated_at=datetime(2001, 2, 4, 4, 5, 6, tzinfo=timezone.utc),
    )
    return {"case": _case_summary(project)}


@pytest.mark.parametrize("expected", [
    "Synthetic cotton shirt inquiry", "2001-02-03T04:05:06+00:00", "2001-02-04T04:05:06+00:00",
])
def test_markdown_export_preserves_actual_case_metadata(expected):
    assert expected in _markdown_export(case_payload())


def test_missing_case_metadata_stays_unknown():
    report = _markdown_export({"case": {"case_id": "legacy", "case_state": "inquiry", "status": "active"}})
    marker = "## Case metadata\n\n```json\n"
    assert marker in report
    metadata = json.loads(report.split(marker, 1)[1].split("\n```", 1)[0])
    assert metadata["title"] is None
    assert metadata["created_at"] is None
    assert metadata["updated_at"] is None


def test_case_metadata_does_not_replace_existing_history():
    payload = case_payload()
    payload.update(messages=[{"message_text": "Saved canonical message"}],
                   drafts=[{"status": "rejected"}], audit=[{"event_type": "DRAFT_REJECTED"}])
    report = _markdown_export(payload)
    for expected in ("synthetic-export-case", "State: inquiry", "Status: active",
                     "Saved canonical message", "rejected", "DRAFT_REJECTED"):
        assert expected in report
