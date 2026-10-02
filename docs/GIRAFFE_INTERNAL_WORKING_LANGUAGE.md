# Giraffe Product Language and Data Boundary

Reconciled: 2026-10-02. The product language for work and interaction is **standard English**. Non-English input and output are supported through **dynamic translation by `giraffe-language-skill`**.

## Workflow ingress

Non-English user, operator, buyer, supplier, IM, email, marketplace, file/image-extracted or other business text is translated by the language module before it enters the product workflow. Aivan consumes the module's canonical English structured RFQ packet for business extraction, supplier routing, GLTG/GPM inputs, graph writes and drafts.

Do not give raw non-English business input to Aivan's requirement LLM or deterministic extraction fallback. Do not build product-local translation prompts, multilingual alias maps, a competing translation service or static locale bundles as a substitute for the language module. If valid canonicalization is unavailable, expose that limitation and retain a safe user correction/retry path; do not guess canonical facts.

English inputs may use the applicable normal English workflow. Keep original source identifiers and permitted evidence references so translation/extraction can be traced without redefining inference as an observed fact.

## Database rule

Except for **enterprise/user profile information**, the DB may store only standard-English textual business content. This applies to business history and process state, requirements, messages, drafts, quotations, order details, dependency explanations, events, audit descriptions and free-text metadata.

The profile exception concerns enterprise/user profile information, such as their names and profile particulars. It is not a blanket exception for conversations, transactions, attachments, drafts or arbitrary business metadata.

Earlier guidance permitting non-English source text alongside a canonical English field is superseded. Do not add a `raw_text` field, audit-text exception or side store to evade the rule. Use allowed source references, hashes and canonical English content as appropriate. Non-linguistic identifiers, hashes and numeric values are not prose that needs invented translation.

Existing non-English records must be inventoried and preserved for an authorized migration/translation plan. This documentation change does not delete data, run a migration or authorize irreversible cleanup.


The DB text-language rule does not prohibit non-English file/image input or require rewriting image pixels. Translate extracted business text through the language module before workflow and storage. File references and binary inputs follow the selected safe storage/authorization boundary; they do not justify retaining prohibited raw business text in DB fields or an evasion side store.

## Output

The default interaction is standard English. When non-English output is requested, obtain it dynamically through `giraffe-language-skill`. Localized display/send text is not an alternative DB truth. Persist the canonical English business record and permissible delivery/source evidence; do not store the translated non-English business text in the DB outside the profile exception.

A translation or language model response cannot approve a draft, supply unobserved supplier/material facts, or establish delivery. Preserve known uncertainty, source relationships and human review across localization.

## Tests and implementation reconciliation

Verify:

1. Non-English input reaches the language module before business workflow/extraction.
2. Invalid/unavailable canonicalization does not silently enter a raw-language fallback.
3. Aivan consumes the canonical English structured RFQ packet.
4. Non-profile DB writes reject non-English textual business content, including nested metadata and audit descriptions.
5. Enterprise/user profile exceptions remain narrowly scoped.
6. Requested non-English output uses dynamic language-skill translation without non-English business persistence.
7. Canonical facts, DB recovery, authorization and draft/delivery status survive the language boundary.

Existing translation catalogs, provider-specific checks and proofreading implementation may be preserved as engineering assets. A mandatory fixed set of FR/ES/DE/KO/JA catalogs, a model brand or a static-catalog readiness gate is not established by the current product definition. Record any runtime conflict for a scoped code change; do not silently disable safeguards or claim it has already been fixed.
