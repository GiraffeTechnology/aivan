# Giraffe Internal Working Language

## P0 Global Rule

Standard English is the only internal working language across Giraffe products.

All raw multilingual user/operator/customer input must pass through `giraffe-language-skill` before any product workflow code extracts business fields, evaluates supplier routing, runs GLTG, writes graph data, creates QC test points, generates decision packets, or creates outbound drafts.

After internal work is complete, user-facing output is localized into the target language requested by the user.

This is a P0 architecture rule. Any implementation that bypasses it is invalid.

---

## AIVAN Enforcement

AIVAN does not own multilingual RFQ extraction.

For non-English RFQ input:

- `giraffe-language-skill` must normalize the raw message into canonical English.
- `giraffe-language-skill` must produce the structured RFQ packet used for quantity, product, destination, lead time, quality, supplier constraints, logistics requirements, pricing intent, and user intent.
- AIVAN must not call its requirement LLM with raw non-English business text.
- AIVAN must not run deterministic fallback extraction over raw non-English business text.
- AIVAN must not infer canonical product, category, destination, material, quality level, supplier capability, price, or lead time from raw non-English text.
- If language-skill is unavailable or cannot produce a valid canonical packet, AIVAN blocks local extraction and asks for canonicalization / operator confirmation instead of guessing fields.
- GLTG, supplier routing, Giraffe DB graph writes, and outbound draft creation must not run from raw non-English input.

English RFQs may continue through AIVAN's existing local LLM and deterministic fallback path, with language-skill normalization used when available.

---

## Output Localization

Internally, product workflow state remains canonical English.

User-visible operator replies, approval summaries, customer drafts, supplier drafts, QC reports, and decision summaries use language metadata from `giraffe-language-skill`, including:

- `requested_output_language`
- `final_output_language`
- `detected_language`
- source conversation language

If explicit output metadata is absent, the system may fall back to the source language.

Localized output is not the internal source of truth. The canonical English packet remains the audit source.

---

## Prohibited In Product Repos

Product repositories, including AIVAN, must not add:

- internal RFQ translation prompts such as `REQUIREMENT_TRANSLATION_SYSTEM`
- multilingual city alias maps
- destination alias maps
- product alias maps
- SKU alias maps
- material alias maps
- quality alias maps
- supplier alias or capability maps
- category keyword maps
- raw non-English field extraction paths that bypass `giraffe-language-skill`
- LLM extraction directly from raw non-English business text

Those rules belong in `giraffe-language-skill`, canonical resolver services, or Giraffe DB canonical data layers so all Giraffe products share one canonical language boundary.

---

## Required Tests

Each relevant product repo must include tests proving:

1. Non-English input calls `giraffe-language-skill` before business extraction.
2. Non-English input without a valid language-skill packet is blocked.
3. Local LLM does not receive raw non-English business text.
4. Deterministic fallback does not canonicalize raw non-English product, destination, category, material, quality, or supplier information.
5. Final user-facing output is localized into the target language requested by the user.
6. Canonical English internal state is preserved separately from localized output.
7. Static guards fail if product repos add alias maps or multilingual business-semantic hardcoding.

---

## Final Required Statement

P0 Global Rule Enforced:

Standard English is the only internal working language across Giraffe products.
All raw multilingual input must pass through `giraffe-language-skill` before product workflow.
After internal work is complete, user-facing output is localized into the target language requested by the user.
