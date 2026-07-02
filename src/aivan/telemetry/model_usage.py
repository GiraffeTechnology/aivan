"""Model-usage telemetry.

Records every model call — AIVAN-direct local LLM, language-skill local model,
GLTG-internal local LLM, and any confirmed external escalation — so the
benchmark can answer where local small-model tokens actually buy value and prove
that no external provider API is called automatically in private-domain mode.

The recorder is deliberately process-local and cheap: a benchmark run creates a
:class:`ModelUsageRecorder`, passes it through the workflow, and reads the
aggregate at the end. Nothing here performs I/O.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from aivan.llm.policy import is_external_provider


def estimate_tokens(text: str | None) -> int:
    """Cheap, provider-agnostic token estimate (~4 chars/token, CJK ~1.5)."""
    if not text:
        return 0
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    wide_chars = len(text) - ascii_chars
    return max(1, round(ascii_chars / 4 + wide_chars / 1.5))


@dataclass
class ProviderCallEvent:
    """Emitted by the LLM gateway for every provider call attempt.

    Lets the benchmark read what *actually* happened (which provider/model ran,
    whether it fell back to mock, whether an external API was reached) instead of
    guessing from env vars.
    """

    task: str
    configured_provider: str
    used_provider: str  # provider that actually produced the result ("none" if none)
    model: str = ""
    ok: bool = False
    fell_back_to_mock: bool = False
    external_api_called: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class ModelCall:
    task: str
    provider: str
    model: str
    component: str = "aivan"  # aivan | language_skill | gltg
    external_api_called: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    authoritative_for_result: bool = False
    fallback_reason: str = ""
    value_added: str = "unknown"  # improved | neutral | wasted | unknown
    approval_id: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ModelUsageRecorder:
    calls: list[ModelCall] = field(default_factory=list)

    def record(self, call: ModelCall) -> ModelCall:
        self.calls.append(call)
        return call

    def record_call(
        self,
        task: str,
        provider: str,
        model: str = "",
        component: str = "aivan",
        input_text: str | None = None,
        output_text: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: float = 0.0,
        authoritative_for_result: bool = False,
        fallback_reason: str = "",
        value_added: str = "unknown",
        approval_id: str = "",
    ) -> ModelCall:
        return self.record(
            ModelCall(
                task=task,
                provider=provider,
                model=model,
                component=component,
                external_api_called=is_external_provider(provider),
                input_tokens=input_tokens if input_tokens is not None else estimate_tokens(input_text),
                output_tokens=output_tokens if output_tokens is not None else estimate_tokens(output_text),
                latency_ms=latency_ms,
                authoritative_for_result=authoritative_for_result,
                fallback_reason=fallback_reason,
                value_added=value_added,
                approval_id=approval_id,
            )
        )

    @contextmanager
    def timed(self, task: str, provider: str, model: str = "", component: str = "aivan", **kwargs):
        """Time a model call; usage: ``with recorder.timed(...) as call: ...``."""
        started = time.perf_counter()
        call = ModelCall(
            task=task,
            provider=provider,
            model=model,
            component=component,
            external_api_called=is_external_provider(provider),
            **kwargs,
        )
        try:
            yield call
        finally:
            call.latency_ms = (time.perf_counter() - started) * 1000.0
            self.record(call)

    # ---- aggregates -------------------------------------------------- #
    @property
    def llm_call_count(self) -> int:
        return len(self.calls)

    @property
    def external_api_calls(self) -> list[ModelCall]:
        return [c for c in self.calls if c.external_api_called]

    @property
    def external_api_called(self) -> bool:
        return any(c.external_api_called for c in self.calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_latency_ms(self) -> float:
        return sum(c.latency_ms for c in self.calls)

    def calls_for_component(self, component: str) -> list[ModelCall]:
        return [c for c in self.calls if c.component == component]

    def summary(self) -> dict:
        gltg_calls = self.calls_for_component("gltg")
        return {
            "llm_call_count": self.llm_call_count,
            "external_api_called": self.external_api_called,
            "external_api_call_count": len(self.external_api_calls),
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": round(self.total_latency_ms, 3),
            "gltg_local_llm_called": bool(gltg_calls),
            "gltg_local_llm_input_tokens": sum(c.input_tokens for c in gltg_calls),
            "gltg_local_llm_output_tokens": sum(c.output_tokens for c in gltg_calls),
            "gltg_external_llm_api_called": any(c.external_api_called for c in gltg_calls),
            "calls": [asdict(c) for c in self.calls],
        }
