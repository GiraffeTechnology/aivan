"""Configuration and call profiles for the local-LLM Token Guard.

Every value is read from the environment with a conservative default so the
guard is safe even when nothing is configured. Nothing here hardcodes a host
address — the Ollama endpoint is always taken from ``OLLAMA_BASE_URL`` in the
provider, never from this module.

The Token Guard exists to make it *impossible* for a caller to send an
unbounded, uncancellable request to the single-CPU production Ollama box. See
``guard.py`` for the enforcement itself; this module only supplies the numbers
and the fixed set of call profiles.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── Hard limits and budgets (env-overridable, safe defaults) ────────────────
def guard_enabled() -> bool:
    # Only an explicit opt-out disables the guard; it is on by default.
    return _env_bool("LLM_GUARD_ENABLED", True)


def hard_max_num_predict() -> int:
    return _env_int("LLM_HARD_MAX_NUM_PREDICT", 2048)


def default_num_predict() -> int:
    return _env_int("LLM_DEFAULT_NUM_PREDICT", 512)


def think_default() -> bool:
    return _env_bool("LLM_THINK_DEFAULT", False)


def think_num_predict() -> int:
    return _env_int("LLM_THINK_NUM_PREDICT", 1024)


def context_window() -> int:
    return _env_int("LLM_CONTEXT_WINDOW", 4096)


def max_prompt_tokens_ratio() -> float:
    return _env_float("LLM_MAX_PROMPT_TOKENS_RATIO", 0.75)


def concurrency() -> int:
    return max(1, _env_int("LLM_CONCURRENCY", 1))


def queue_wait_timeout_s() -> float:
    return _env_float("LLM_QUEUE_WAIT_TIMEOUT_S", 30.0)


def load_time_buffer_s() -> float:
    return _env_float("LLM_LOAD_TIME_BUFFER_S", 15.0)


def gen_speed_tps() -> float:
    return max(0.1, _env_float("LLM_GEN_SPEED_TPS", 5.0))


def prompt_speed_tps() -> float:
    return max(0.1, _env_float("LLM_PROMPT_SPEED_TPS", 15.0))


def timeout_safety_factor() -> float:
    return _env_float("LLM_TIMEOUT_SAFETY_FACTOR", 1.5)


def max_inference_timeout_s() -> float:
    """Absolute per-inference wall-clock ceiling.

    Supplement to the base PRD: a single AI inference may never run longer than
    this. The token-budget formula can propose a much larger timeout (minutes),
    but the effective timeout is always ``min(computed, this)``. When it fires
    the in-flight Ollama stream is force-aborted (circuit-break), so one runaway
    request can never pin the production CPU for minutes.
    """
    return _env_float("LLM_MAX_INFERENCE_TIMEOUT_S", 60.0)


# ── Call profiles ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LlmProfile:
    name: str
    think: bool
    num_predict: int
    temperature: float


# Business code selects a profile by intent; it never free-forms think/budget.
PROFILES: dict[str, LlmProfile] = {
    "qa_short": LlmProfile("qa_short", think=False, num_predict=256, temperature=0.0),
    "qa_standard": LlmProfile("qa_standard", think=False, num_predict=512, temperature=0.0),
    "reasoning": LlmProfile("reasoning", think=True, num_predict=1024, temperature=0.2),
    "reasoning_max": LlmProfile("reasoning_max", think=True, num_predict=2048, temperature=0.2),
}

DEFAULT_PROFILE = "qa_standard"

# Map internal task names to a profile. Unknown tasks fall back to the default.
# These are intent hints only; none of them may exceed the hard cap.
TASK_PROFILE: dict[str, str] = {
    "requirement_structuring": "qa_standard",
    "aivan_event_classification": "qa_short",
    "aivan_strategy_interpretation": "qa_standard",
    "aivan_supplier_email_draft": "qa_standard",
}


def resolve_profile(profile: str | None, task: str | None = None) -> LlmProfile:
    """Resolve an effective profile from an explicit name or a task hint.

    An unrecognized profile name is treated as the default rather than raising,
    so a business typo degrades safely to the most restrictive common profile.
    """
    if profile and profile in PROFILES:
        return PROFILES[profile]
    if task and task in TASK_PROFILE:
        return PROFILES[TASK_PROFILE[task]]
    return PROFILES[DEFAULT_PROFILE]
