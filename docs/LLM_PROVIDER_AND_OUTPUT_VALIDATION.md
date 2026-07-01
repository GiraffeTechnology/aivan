# LLM Provider and Output Validation

## Provider adapters

Provider-specific clients live behind the `LLMProvider` interface
(`src/aivan/llm/base.py`) and are selected by `AIVAN_LLM_PROVIDER`
(`mock` | `ollama` | `openai` | `anthropic` | `google` | `deepseek` | `qwen`).
**Qwen3.5 may be a default local model, but Giraffe is not a Qwen ecosystem
product** — providers are interchangeable behind the adapter.

## Output validation & error classification

Invalid or empty model output is never treated as success. Providers raise
`LLMProviderError` (`src/aivan/llm/errors.py`) with a normalized `error_code`:

| Condition | error_code | retry |
| --- | --- | --- |
| empty / whitespace / `null` body, or `{}` object | `LLM_EMPTY_RESPONSE` | at most once |
| malformed / truncated JSON | `LLM_INVALID_JSON` | no |
| valid JSON but not an object (array / scalar) | `LLM_PROVIDER_UNSUPPORTED_RESPONSE` | no |
| provider timeout | `LLM_PROVIDER_TIMEOUT` | up to `AIVAN_LLM_MAX_RETRIES` |
| connection / transport / HTTP error | `LLM_PROVIDER_CONNECTION_ERROR` | up to `AIVAN_LLM_MAX_RETRIES` |
| schema validation failed (caller) | `LLM_SCHEMA_VALIDATION_FAILED` | no |

Every `LLMProviderError` carries `manual_review_required=True` and a
`to_manual_review_assessment()` payload:

```json
{"ok": false, "error_code": "LLM_EMPTY_RESPONSE", "provider": "ollama",
 "model": "...", "manual_review_required": true, "retryable": true}
```

Text-around-JSON and code-fenced JSON are recovered when a valid object can be
extracted.

## Secrets

The `LLMProviderError` message contains only the error code, provider name, and
a coarse non-sensitive detail tag. It never includes the model name, prompts, or
raw provider bodies, so failures cannot leak private trade prompts into logs.

## Gateway fail-closed policy

`llm_complete_json` (`src/aivan/llm/gateway.py`) **fails closed**: it does not
silently substitute a fabricated `MockLLMProvider` result for a real provider
failure. Mock fallback is permitted only when the provider is `mock` or
`AIVAN_TEST_MODE` is enabled. In production, callers catch the error and degrade
to deterministic rule-based parsing (transparent), or surface the failure.
