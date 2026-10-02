"""English defaults and examples without changing multilingual runtime contracts."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aivan.agents.requirement_agent import _detect_missing_fields, _deterministic_parse
from aivan.schemas.requirement import BuyerRequirement


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("apparel", {
            "quantity": "What is the order quantity?",
            "product_type": "What is the product?",
            "fabric_material": "What is the fabric or material?",
            "gsm": "What is the fabric weight in GSM?",
            "color": "What is the color?",
            "size_ratio": "What is the size ratio?",
            "packaging": "What is the packaging type?",
            "destination": "What is the destination?",
            "delivery_days": "Within how many days is delivery required?",
        }),
        ("cnc", {
            "quantity": "What is the order quantity?",
            "material_spec": "What is the material specification?",
            "tolerance": "What are the tolerance requirements?",
            "destination": "What is the destination?",
            "delivery_days": "Within how many days is delivery required?",
        }),
    ],
)
def test_generic_missing_field_questions_are_english(category, expected):
    fields = _detect_missing_fields(BuyerRequirement(category=category))
    assert [(field.field_name, field.question) for field in fields] == list(expected.items())


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, "Your request has been received."),
        ({"reply_text": " ", "message": ""}, "Your request has been received."),
        ({"reply_text": "  Explicit reply  ", "message": "Internal summary"}, "Explicit reply"),
        ({"user_control_message": "Review the draft.", "message": "Internal summary"}, "Review the draft."),
        ({"message": "Internal summary"}, "Internal summary"),
    ],
)
def test_skill_reply_fallback_is_english_and_keeps_existing_precedence(data, expected):
    from aivan.api.main import _skill_response

    original = {"project_id": "example-project", "action": "review_required", **data}
    result = _skill_response(SimpleNamespace(model_dump=lambda: dict(original)))
    assert result["status"] == "ok"
    assert result["output"] == result["reply_text"] == expected
    assert result["project_id"] == "example-project"
    assert result["action"] == "review_required"


def test_english_demo_messages_preserve_the_example_business_facts():
    root = Path(__file__).resolve().parents[1] / "data" / "demo_messages"
    inquiry = json.loads((root / "customer_inquiry_01.json").read_text())
    clarification = json.loads((root / "customer_clarification_01.json").read_text())
    assert inquiry["message_text"].isascii()
    assert clarification["message_text"].isascii()
    assert inquiry["conversation_id"] == clarification["conversation_id"]
    assert clarification["in_reply_to_message_id"] == inquiry["message_id"]
    numeric = _deterministic_parse(inquiry["message_text"])
    assert numeric == {
        "quantity": 10000, "gsm": 180, "delivery_days": 45,
        "target_unit_price": 4.80, "incoterms": "DDP", "logistics_preference": "air",
    }
    for detail in ("white", "pure cotton men's shirts", "Vancouver", "20/40/30/10", "individually bagged"):
        assert detail in inquiry["message_text"]
    for detail in ("20:40:30:10", "180gsm pure cotton", "white only", "OPP bag", "12 pieces per carton", "30% advance T/T", "balance against a copy of the bill of lading", "OEKO-TEX"):
        assert detail in clarification["message_text"]
