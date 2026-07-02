"""P0 internal working language policy guardrails."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_aivan_does_not_define_internal_translation_prompt_or_semantic_alias_maps():
    """AIVAN must not own multilingual business extraction or alias rules.

    Non-English normalization and semantic field extraction belong to the shared
    giraffe-language-skill layer. AIVAN may render localized user-facing output,
        but it must not define product/city/material/quality/supplier/category
        alias tables or an internal RFQ translation prompt.
    """
    forbidden = (
        "REQUIREMENT_TRANSLATION_SYSTEM",
        "MATERIAL_ALIAS",
        "MATERIAL_ALIASES",
        "QUALITY_ALIAS",
        "QUALITY_ALIASES",
        "SUPPLIER_ALIAS",
        "SUPPLIER_ALIASES",
        "SUPPLIER_CAPABILITY_ALIAS",
        "SUPPLIER_CAPABILITY_ALIASES",
        "CATEGORY_KEYWORD",
        "CATEGORY_KEYWORDS",
        "CATEGORY_ALIAS",
        "CATEGORY_ALIASES",
        "DESTINATION_ALIAS",
        "DESTINATION_ALIASES",
        "CITY_ALIAS",
        "CITY_ALIASES",
        "SKU_ALIAS",
        "SKU_ALIASES",
        "PRODUCT_ALIAS",
        "PRODUCT_ALIASES",
        "MULTILINGUAL_RFQ_ALIAS",
        "MULTILINGUAL_RFQ_ALIASES",
    )
    offenders: list[str] = []
    for path in (REPO_ROOT / "src" / "aivan").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token}")

    assert offenders == []
