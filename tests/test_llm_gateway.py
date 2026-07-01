"""Tests for aiven.llm.gateway — verifies llm_complete_json works with mock provider."""
import os
import pytest

os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")

from aivan.llm.gateway import llm_complete_json, reset_provider


@pytest.fixture(autouse=True)
def reset_llm_provider():
    """Reset the provider singleton between tests."""
    reset_provider()
    yield
    reset_provider()


def test_llm_complete_json_returns_dict():
    result = llm_complete_json(
        task="requirement_structuring",
        system_prompt="You are a helpful assistant.",
        user_prompt="I need 10000 pcs white cotton shirts.",
    )
    assert isinstance(result, dict)


def test_llm_complete_json_no_exception_on_unknown_task():
    result = llm_complete_json(
        task="some_unknown_task_xyz",
        system_prompt="sys",
        user_prompt="user",
    )
    assert isinstance(result, dict)


def test_llm_complete_json_with_schema_hint():
    result = llm_complete_json(
        task="requirement_structuring",
        system_prompt="sys",
        user_prompt="10000 shirts",
        schema_hint={"category": "string"},
    )
    assert isinstance(result, dict)


def test_llm_complete_json_with_temperature():
    result = llm_complete_json(
        task="supplier_inquiry_drafting",
        system_prompt="sys",
        user_prompt="source shirts",
        temperature=0.7,
    )
    assert isinstance(result, dict)


def test_private_domain_test_mode_disables_llm_api_calls(monkeypatch):
    """With the LLM API disabled, no provider is reached and the call raises."""
    from aivan.llm import gateway
    from aivan.llm.gateway import LLMApiDisabledError

    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "false")
    reset_provider()

    # A provider must never be built or invoked while disabled.
    def _boom(*args, **kwargs):
        raise AssertionError("no LLM provider may be built while the API is disabled")

    monkeypatch.setattr(gateway, "_build_provider", _boom)

    with pytest.raises(LLMApiDisabledError):
        llm_complete_json(
            task="requirement_structuring",
            system_prompt="sys",
            user_prompt="I need 10000 pcs white cotton shirts.",
        )


def test_provider_disabled_name_also_blocks_llm_calls(monkeypatch):
    from aivan.llm.gateway import LLMApiDisabledError

    monkeypatch.delenv("AIVAN_LLM_API_ENABLED", raising=False)
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "disabled")
    reset_provider()

    with pytest.raises(LLMApiDisabledError):
        llm_complete_json(task="requirement_structuring", system_prompt="s", user_prompt="u")


def test_llm_complete_json_falls_back_on_provider_error(monkeypatch):
    """If the provider raises, gateway falls back to MockLLMProvider."""
    def bad_complete(*args, **kwargs):
        raise RuntimeError("Simulated provider failure")

    reset_provider()
    from aivan.llm.gateway import get_provider
    provider = get_provider()
    monkeypatch.setattr(provider, "complete_json", bad_complete)

    result = llm_complete_json(
        task="requirement_structuring",
        system_prompt="sys",
        user_prompt="test fallback",
    )
    assert isinstance(result, dict)
