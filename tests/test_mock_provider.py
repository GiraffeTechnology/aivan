"""Tests for MockLLMProvider — verifies all major task types return dicts."""
import pytest
from aiven.llm.providers.mock_provider import MockLLMProvider


@pytest.fixture
def provider():
    return MockLLMProvider()


def test_provider_name(provider):
    assert provider.provider_name == "mock"


def test_requirement_structuring(provider):
    result = provider.complete_json(
        task="requirement_structuring",
        system_prompt="sys",
        user_prompt="10000 shirts",
        schema_hint={},
    )
    assert isinstance(result, dict)
    assert "category" in result


def test_missing_field_clarification(provider):
    result = provider.complete_json(
        task="missing_field_clarification",
        system_prompt="sys",
        user_prompt="clarify",
        schema_hint={},
    )
    assert isinstance(result, dict)
    assert "missing_fields" in result
    assert isinstance(result["missing_fields"], list)


def test_supplier_inquiry_drafting(provider):
    result = provider.complete_json(
        task="supplier_inquiry_drafting",
        system_prompt="sys",
        user_prompt="draft inquiry",
        schema_hint={},
    )
    assert isinstance(result, dict)
    assert "message_text" in result


def test_supplier_response_parsing(provider):
    result = provider.complete_json(
        task="supplier_response_parsing",
        system_prompt="sys",
        user_prompt="parse reply",
        schema_hint={},
    )
    assert isinstance(result, dict)
    assert "unit_price" in result


def test_buyer_option_generation(provider):
    result = provider.complete_json(
        task="buyer_option_generation",
        system_prompt="sys",
        user_prompt="generate options",
        schema_hint={},
    )
    assert isinstance(result, dict)
    assert "options" in result
    assert len(result["options"]) == 3


def test_default_fallback(provider):
    result = provider.complete_json(
        task="totally_unknown_task_type",
        system_prompt="sys",
        user_prompt="anything",
        schema_hint={},
    )
    assert isinstance(result, dict)
    assert "result" in result


def test_task_name_normalization(provider):
    """Underscores, hyphens, spaces should all resolve to the same response."""
    r1 = provider.complete_json("requirement_structuring", "", "", {})
    r2 = provider.complete_json("requirement-structuring", "", "", {})
    r3 = provider.complete_json("requirement structuring", "", "", {})
    assert r1 == r2 == r3


def test_complete_json_returns_new_dict_each_call(provider):
    """Mutating the returned dict should not affect subsequent calls."""
    r1 = provider.complete_json("requirement_structuring", "", "", {})
    r1["injected_key"] = "should_not_persist"
    r2 = provider.complete_json("requirement_structuring", "", "", {})
    assert "injected_key" not in r2
