import os
from aivan.llm.base import LLMProvider
from aivan.llm.config import get_llm_provider_name
from aivan.llm.policy import (
    ExternalModelApiRequiresApprovalError,
    assert_provider_allowed,
    llm_api_enabled,
)

_provider_instance: LLMProvider | None = None

def _build_provider(name: str) -> LLMProvider:
    if name == "mock":
        from aivan.llm.providers.mock_provider import MockLLMProvider
        return MockLLMProvider()
    elif name in ("openai", "chatgpt", "openai_compatible"):
        from aivan.llm.providers.openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif name in ("anthropic", "claude"):
        from aivan.llm.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif name in ("google", "gemini"):
        from aivan.llm.providers.google_provider import GoogleProvider
        return GoogleProvider()
    elif name == "deepseek":
        from aivan.llm.providers.deepseek_provider import DeepSeekProvider
        return DeepSeekProvider()
    elif name == "qwen":
        from aivan.llm.providers.qwen_provider import QwenProvider
        return QwenProvider()
    elif name == "ollama":
        from aivan.llm.providers.ollama_provider import OllamaProvider
        return OllamaProvider()
    else:
        from aivan.llm.providers.mock_provider import MockLLMProvider
        return MockLLMProvider()

def build_llm_provider(task: str | None = None) -> LLMProvider:
    """Build the configured LLM provider, enforcing the external-model policy.

    Raises ``ExternalModelApiRequiresApprovalError`` when an external provider is
    requested but automatic external calls are disabled and no approval packet is
    active. Local/private-domain providers (mock, ollama) always build.
    """
    name = get_llm_provider_name()
    assert_provider_allowed(name, task)
    return _build_provider(name)


def get_provider() -> LLMProvider:
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = _build_provider(get_llm_provider_name())
    return _provider_instance

def reset_provider():
    global _provider_instance
    _provider_instance = None

def llm_complete_json(
    task: str,
    system_prompt: str,
    user_prompt: str,
    schema_hint: dict = None,
    temperature: float = 0.0,
) -> dict:
    # Enforce the private-domain policy before any provider work. This must not
    # be swallowed by the mock fallback below: an external provider without
    # approval is a hard, auditable stop, never a silent cloud fallback.
    assert_provider_allowed(get_llm_provider_name(), task)
    if not llm_api_enabled():
        # Zero-model regime: no extraction. Callers fall back to deterministic
        # raw-evidence parsing instead of receiving fabricated canonical fields.
        return {}
    provider = get_provider()
    try:
        result = provider.complete_json(task, system_prompt, user_prompt, schema_hint or {}, temperature)
        if not isinstance(result, dict):
            result = {"result": str(result)}
        return result
    except ExternalModelApiRequiresApprovalError:
        raise
    except Exception:
        from aivan.llm.providers.mock_provider import MockLLMProvider
        return MockLLMProvider().complete_json(task, system_prompt, user_prompt, schema_hint or {}, temperature)
