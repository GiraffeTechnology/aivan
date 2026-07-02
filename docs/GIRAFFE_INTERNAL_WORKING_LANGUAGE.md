# Giraffe Internal Working Language

## P0 Global Rule

Standard English is the only internal working language across Giraffe products.

All raw multilingual user input must pass through `giraffe-language-skill` before
product workflow code extracts business fields, evaluates supplier routing,
runs GLTG, writes graph data, or creates outbound drafts.

After internal work is complete, user-facing output is localized into the target
language requested by the user.

## AIVAN Enforcement

AIVAN does not own multilingual RFQ extraction. For non-English RFQ input:

- `giraffe-language-skill` must normalize the raw message into canonical English.
- `giraffe-language-skill` must produce the structured RFQ packet used for
  quantity, product, destination, lead time, quality, and intent.
- AIVAN must not call its requirement LLM with raw non-English business text.
- AIVAN must not run deterministic fallback extraction over raw non-English
  business text.
- If language-skill is unavailable or cannot produce a valid RFQ packet, AIVAN
  blocks local extraction and asks for canonicalization/confirmation instead of
  guessing fields.

English RFQs may continue through AIVAN's existing local LLM and deterministic
fallback path, with language-skill normalization used when available.

## Output Localization

Internally, product workflow state remains canonical English. User-visible
operator replies and approval summaries use language metadata from
`giraffe-language-skill`, including `requested_output_language` and
`final_output_language`, and fall back to the source language only when explicit
output metadata is absent.

## Prohibited In Product Repos

Product repositories, including AIVAN, must not add:

- internal RFQ translation prompts such as `REQUIREMENT_TRANSLATION_SYSTEM`
- multilingual city, destination, product, SKU, quality, supplier, or category
  alias maps for business extraction
- raw non-English field extraction paths that bypass `giraffe-language-skill`

Those rules belong in `giraffe-language-skill` so all Giraffe products share one
canonical language boundary.
