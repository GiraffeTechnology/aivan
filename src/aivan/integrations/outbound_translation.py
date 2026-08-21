"""Dedicated outbound translation with optional Qwen proofreading.

Translation generation is always delegated to ``giraffe-language-skill``.
The local qwen3.5:9b model can only inspect and proofread the generated target
text; it never receives authority to create a translation from source text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aivan.integrations.language_skill_client import LanguageSkillClient


SUPPORTED_TARGETS = {"en", "zh", "zht", "fr", "es", "de", "ko", "ja"}
GENERATED_TARGETS = {"fr", "es", "de", "ko", "ja"}


class TranslationUnavailable(RuntimeError):
    """Raised when the dedicated translator cannot provide trusted output."""


@dataclass(frozen=True)
class OutboundTranslation:
    text: str
    target_language: str
    provider: str
    model: str
    backend: str
    proofread: bool = False
    proofreader_model: str | None = None


def translate_authoritative_english(
    canonical_english: str,
    target_language: str,
    *,
    target_channel: str = "myaivan",
    message_type: str = "operator_reply",
    client: LanguageSkillClient | None = None,
) -> OutboundTranslation:
    """Generate a target translation from authoritative English only."""
    target = target_language.strip().lower()
    if target not in GENERATED_TARGETS:
        raise ValueError("dedicated generation is only valid for FR/ES/DE/KO/JA")
    source = canonical_english.strip()
    if not source:
        raise ValueError("canonical English source is required")

    client = client or LanguageSkillClient()
    models = client.models()
    if not models.ok or not isinstance(models.data, dict):
        raise TranslationUnavailable("translation model inventory unavailable")
    provider, model, backend = _provider_identity(models.data)
    if provider in {"", "mock"} or not (model or backend):
        raise TranslationUnavailable("dedicated translation backend is not production-ready")

    result = client.render_outbound(
        target_language=target,
        canonical_text=source,
        target_channel=target_channel,
        message_type=message_type,
        business_refs={"source_authority": "canonical_english"},
    )
    if not result.ok or not isinstance(result.data, dict):
        raise TranslationUnavailable("dedicated outbound translation failed")
    translated = _translated_text(result.data)
    if not translated:
        raise TranslationUnavailable("dedicated translator returned empty output")

    result_provider = str(result.data.get("provider") or provider).strip().lower()
    if result_provider in {"", "mock"}:
        raise TranslationUnavailable("outbound translation used an untrusted provider")
    result_model = str(result.data.get("model") or model).strip()
    proofreader = result.data.get("proofreader")
    proofread = False
    proofreader_model = None
    if isinstance(proofreader, dict):
        role = str(proofreader.get("role") or "").strip().lower()
        proofreader_model = str(proofreader.get("model") or "").strip() or None
        if role != "proofread-only" or proofreader_model != "qwen3.5:9b":
            raise TranslationUnavailable("proofreader boundary is not trustworthy")
        proofread = str(proofreader.get("status") or "") in {"accepted", "revised"}
    return OutboundTranslation(
        text=translated,
        target_language=target,
        provider=result_provider,
        model=result_model,
        backend=backend,
        proofread=proofread,
        proofreader_model=proofreader_model,
    )


def _provider_identity(data: dict[str, Any]) -> tuple[str, str, str]:
    item: dict[str, Any] = data
    models = data.get("models")
    if isinstance(models, list) and models and isinstance(models[0], dict):
        item = models[0]
    provider = str(item.get("provider") or data.get("provider") or "").strip().lower()
    model = str(item.get("model") or item.get("name") or data.get("model") or "").strip()
    if not model and isinstance(models, list):
        model = ",".join(str(value) for value in models if str(value).strip())
    backend = str(item.get("backend") or data.get("backend") or "").strip()
    if not backend and provider == "ctranslate2":
        backend = "ctranslate2"
    return provider, model, backend


def _translated_text(data: dict[str, Any]) -> str:
    for key in ("rendered_text", "translated_text", "target_text", "text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    translation = data.get("translation")
    if isinstance(translation, dict):
        for key in ("rendered_text", "translated_text", "target_text", "text"):
            value = translation.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""
