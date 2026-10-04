# Explicit zero-model quote guidance

The existing `AIVAN_LLM_API_ENABLED=false` setting disables both local and
external model calls. GPM honors that setting using the existing Aivan quote
margin arithmetic on the supplied buyer and supplier totals. The numbers remain
bound to the authenticated tenant, case, source quote and GLTG reference and are
persisted through the same private DB packet API.

This is a deterministic quote-total comparison. It is not a mock, a market
benchmark, a complete landed-cost calculation or a model inference. Results use
`human_review_required`, `insufficient_data` and low confidence. The existing
`model_result` compatibility envelope identifies `runtime_status=disabled`,
`model_provider=none` and no model name. Its calculation contains the supplied
totals and their difference; the existing margin helper rounds the ratio to two
decimal places. Missing costs and benchmarks remain unverified.

Disabling model calls does not disable authentication, tenant/object isolation,
private DB persistence, source lineage, idempotency, commercial review or manual
delivery requirements. Replays return the committed packet without recalculating
it. A changed commercial input with the same key remains a conflict. An unavailable
DB remains an error.

With model calls enabled, GPM preserves the provider's failures rather than
switching silently to deterministic or mock output. Hosted provider access obeys
the existing explicit external-model policy before any provider construction or
call. No model download, external call or new approval is performed by this change.

One actual, contactable supplier may proceed to calculation and reviewable drafts.
The feasibility label remains `single`; no additional supplier is invented. An
empty/contactless supplier set still needs selection, and sending or order
confirmation retains its ordinary human authorization.
