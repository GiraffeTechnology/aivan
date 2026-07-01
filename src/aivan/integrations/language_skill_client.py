"""Thin HTTP client for the standalone giraffe-language-skill service.

The Giraffe Language Skill Layer lives in its own service:
    https://github.com/GiraffeTechnology/giraffe-language-skill

It converts multilingual IM/email business messages into canonical English
business packets, applies deterministic extraction + Giraffe domain-glossary
normalization, and renders canonical outbound packets back into a recipient's
target language. AIVAN uses it for RFQ intake canonicalization so that explicit
business facts (quantity, destination, lead time, product) are never lost to a
small local LLM.

This client is the ONLY way AIVAN talks to the language skill. It never parses
locally as a substitute; failures are surfaced as structured results so callers
can fail soft (preserve the raw message, do not hallucinate missing fields).

Configuration (environment):
    AIVAN_LANGUAGE_SKILL_ENABLED          default false
    AIVAN_LANGUAGE_SKILL_BASE_URL         default http://127.0.0.1:8788
    AIVAN_LANGUAGE_SKILL_TIMEOUT_SECONDS  default 10
    AIVAN_LANGUAGE_SKILL_FAIL_SOFT        default true
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8788"
DEFAULT_TIMEOUT_SECONDS = 10.0

# Process-wide transport override. Tests install an httpx.MockTransport here so
# the whole app talks to a faithful in-memory language-skill without a live
# server.
_DEFAULT_TRANSPORT: "httpx.BaseTransport | None" = None


def set_default_transport(transport: "httpx.BaseTransport | None") -> None:
    """Install (or clear) a process-wide default transport for the client."""
    global _DEFAULT_TRANSPORT
    _DEFAULT_TRANSPORT = transport


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    """True when AIVAN is configured to call the language skill."""
    return _env_bool("AIVAN_LANGUAGE_SKILL_ENABLED", False)


def is_fail_soft() -> bool:
    """True when language-skill failures must be swallowed (the safe default)."""
    return _env_bool("AIVAN_LANGUAGE_SKILL_FAIL_SOFT", True)


@dataclass
class LanguageSkillResult:
    """Structured result wrapper. Never raises service failures at the call site."""

    ok: bool
    data: dict | None
    error: str | None
    status_code: int | None


class LanguageSkillClient:
    """Synchronous HTTP client for the giraffe-language-skill API."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("AIVAN_LANGUAGE_SKILL_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        if timeout_seconds is not None:
            self.timeout = timeout_seconds
        else:
            self.timeout = float(
                os.environ.get("AIVAN_LANGUAGE_SKILL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
            )
        # Injectable transport keeps unit tests off the network
        # (httpx.MockTransport). Falls back to the process-wide default.
        self._transport = transport if transport is not None else _DEFAULT_TRANSPORT

    # ------------------------------------------------------------------ #
    # transport
    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, json: dict | None = None) -> LanguageSkillResult:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                resp = client.request(method, url, json=json)
        except httpx.TimeoutException as exc:
            return LanguageSkillResult(False, None, f"language-skill request timed out: {exc}", None)
        except httpx.HTTPError as exc:
            return LanguageSkillResult(False, None, f"language-skill connection error: {exc}", None)

        if resp.status_code >= 400:
            return LanguageSkillResult(
                False,
                None,
                f"language-skill returned HTTP {resp.status_code}: {resp.text[:500]}",
                resp.status_code,
            )
        try:
            return LanguageSkillResult(True, resp.json(), None, resp.status_code)
        except ValueError as exc:
            return LanguageSkillResult(
                False, None, f"language-skill returned invalid JSON: {exc}", resp.status_code
            )

    # ------------------------------------------------------------------ #
    # endpoints
    # ------------------------------------------------------------------ #
    def health(self) -> LanguageSkillResult:
        return self._request("GET", "/healthz")

    def models(self) -> LanguageSkillResult:
        return self._request("GET", "/v1/models")

    def normalize(
        self,
        source_text: str,
        source_language: str = "auto",
        canonical_language: str = "en",
        domain_hint: str | None = None,
        source_channel: str | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> LanguageSkillResult:
        payload: dict[str, Any] = {
            "source_text": source_text,
            "source_language": source_language,
            "canonical_language": canonical_language,
        }
        if domain_hint:
            payload["domain_hint"] = domain_hint
        if source_channel:
            payload["source_channel"] = source_channel
        if conversation_context:
            payload["conversation_context"] = conversation_context
        return self._request("POST", "/v1/inbound/normalize", json=payload)

    def structure_rfq(
        self,
        raw_text: str,
        canonical_text: str | None = None,
        field_evidence: dict[str, Any] | None = None,
        schema_version: str = "trade_rfq.v1",
    ) -> LanguageSkillResult:
        payload: dict[str, Any] = {"raw_text": raw_text, "schema_version": schema_version}
        if canonical_text is not None:
            payload["canonical_text"] = canonical_text
        if field_evidence:
            payload["field_evidence"] = field_evidence
        return self._request("POST", "/v1/structure/rfq", json=payload)

    def structure_apparel_customization(
        self,
        raw_text: str,
        canonical_text: str | None = None,
        field_evidence: dict[str, Any] | None = None,
        schema_version: str = "apparel_customization.v1",
    ) -> LanguageSkillResult:
        payload: dict[str, Any] = {"raw_text": raw_text, "schema_version": schema_version}
        if canonical_text is not None:
            payload["canonical_text"] = canonical_text
        if field_evidence:
            payload["field_evidence"] = field_evidence
        return self._request("POST", "/v1/structure/apparel-customization", json=payload)

    def render_outbound(
        self,
        target_language: str,
        canonical_text: str,
        target_channel: str | None = None,
        message_type: str | None = None,
        business_refs: dict[str, Any] | None = None,
        tone: str | None = None,
    ) -> LanguageSkillResult:
        payload: dict[str, Any] = {
            "target_language": target_language,
            "canonical_text": canonical_text,
        }
        if target_channel:
            payload["target_channel"] = target_channel
        if message_type:
            payload["message_type"] = message_type
        if business_refs:
            payload["business_refs"] = business_refs
        if tone:
            payload["tone"] = tone
        return self._request("POST", "/v1/outbound/render", json=payload)
