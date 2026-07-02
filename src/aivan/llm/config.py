import os

def get_llm_provider_name() -> str:
    return os.environ.get("AIVAN_LLM_PROVIDER", "ollama").lower()

def get_llm_temperature() -> float:
    return float(os.environ.get("AIVAN_LLM_TEMPERATURE", "0"))

def get_llm_timeout() -> int:
    return int(os.environ.get("AIVAN_LLM_TIMEOUT_SECONDS", "30"))

def get_llm_max_retries() -> int:
    return int(os.environ.get("AIVAN_LLM_MAX_RETRIES", "2"))
