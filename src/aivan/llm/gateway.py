import os
from aivan.llm.base import LLMProvider
from aivan.llm.config import get_llm_provider_name

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
    else:
        from aivan.llm.providers.mock_provider import MockLLMProvider
        return MockLLMProvider()

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
    provider = get_provider()
    try:
        result = provider.complete_json(task, system_prompt, user_prompt, schema_hint or {}, temperature)
        if not isinstance(result, dict):
            result = {"result": str(result)}
        return result
    except Exception:
        from aivan.llm.providers.mock_provider import MockLLMProvider
        return MockLLMProvider().complete_json(task, system_prompt, user_prompt, schema_hint or {}, temperature)
