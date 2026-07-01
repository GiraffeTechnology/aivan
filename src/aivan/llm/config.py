import os

# Provider names that explicitly mean "no LLM API may be called" (private-domain
# / test mode). The provider abstraction stays in the codebase; production simply
# configures a real provider instead.
_DISABLED_PROVIDER_NAMES = {"disabled", "none", "off"}
_FALSE_VALUES = {"false", "0", "no", "off"}


def get_llm_provider_name() -> str:
    return os.environ.get("AIVAN_LLM_PROVIDER", "mock").lower()


def is_llm_api_enabled() -> bool:
    """Whether AIVAN is allowed to invoke any LLM provider.

    Returns ``False`` in private-domain / test mode so no buyer data leaves the
    private domain via an LLM API. Disabled when either ``AIVAN_LLM_API_ENABLED``
    is a false-y value or ``AIVAN_LLM_PROVIDER`` is set to ``disabled``/``none``/
    ``off``.
    """
    flag = os.environ.get("AIVAN_LLM_API_ENABLED")
    if flag is not None and flag.strip().lower() in _FALSE_VALUES:
        return False
    if get_llm_provider_name() in _DISABLED_PROVIDER_NAMES:
        return False
    return True

def get_llm_temperature() -> float:
    return float(os.environ.get("AIVAN_LLM_TEMPERATURE", "0"))

def get_llm_timeout() -> int:
    return int(os.environ.get("AIVAN_LLM_TIMEOUT_SECONDS", "30"))

def get_llm_max_retries() -> int:
    return int(os.environ.get("AIVAN_LLM_MAX_RETRIES", "2"))
