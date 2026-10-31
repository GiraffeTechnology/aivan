"""Ephemeral recipient rendering after canonical workflow persistence."""
from aivan.integrations.outbound_translation import (
    TRANSLATED_TARGETS, TranslationUnavailable, translate_authoritative_english,
)


def render_skill_reply(payload: dict, canonical_text: str) -> str:
    requirement = payload.get("requirement") or {}
    extra = requirement.get("extra") or {}
    target = str(extra.get("final_output_language") or extra.get("requested_output_language")
                 or requirement.get("language") or "en").strip().lower()
    if target not in TRANSLATED_TARGETS:
        return canonical_text
    try:
        return translate_authoritative_english(
            canonical_text, target,
            business_refs={"case_id": payload.get("project_id"), "source_authority": "canonical_english"},
        ).text
    except TranslationUnavailable:
        # No fabricated translated success. The complete English reply remains usable.
        return canonical_text
