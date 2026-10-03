# Consumer result integrity

A successful HTTP exchange is not, by itself, a successful business operation.

## Canonical intake

The existing language service remains the only translator. Its normalization
response must contain nonempty text and the requested canonical-language label.
English intake also applies the existing residual-script guard; English Unicode
punctuation and Latin proper names remain supported. `TRANSLATION_MODEL_MISSING`
and `translation.model=unavailable` are failed results, even with HTTP 200.
They produce a sanitized retryable failure before classification, structuring,
or business writes. This validation cannot make an absent translation model work.

## Source quotation and advisory guidance

Buyer-option IDs identify selectable UI versions, not supplier quotations.
Each generated option now retains an immutable source-quotation reference
derived from the actual case, supplier, inbound message and canonical terms.
The `aivan-source-quote-sha256-` reference is an Aivan evidence fingerprint, not a
claim that a giraffe-db quote record already exists. Historical replies without
message identity bind to their persisted text and terms; no provider ID or
numeric revision is invented. A trusted event supplies message identity; an
LLM cannot supply it.

GPM receives this version-specific reference as `quote_id`, actual supplier
price rather than a redacted display zero, selected currency, and the explicit
GLTG reference. The latest reply of the selected supplier must match the option's
reference. Superseded revisions, competing suppliers and inconsistent legacy
terms fail before the GPM request. The idempotency key fingerprints the exact
tenant/actor/trace-bound request, including prices and GLTG lineage. Regenerating
only a random UI ID does not create a new advisory decision. Human approval,
draft invalidation and manual-send requirements remain unchanged.

These consumer checks do not establish CTYun MySQL compatibility, actual model
success, the complete RFQ workflow, or public UI acceptance. Those results must
come from their real service and application paths.

## Mandatory normalization at every intake

RFQ API intake, the legacy CLI trade-agent entry, and text-attachment uploads
require a successful shared language-service normalization result before their
first workflow write. This includes Latin-script and already-English input;
script shape cannot establish that a message is English. Disabling the language
service or receiving an unavailable/invalid result produces
`LANGUAGE_NORMALIZATION_REQUIRED` without persisting the incoming business text.
Enterprise and user profile handling is unchanged.

Consumer unit tests use explicitly synthetic language responses. They establish
ordering, fail-closed behavior, and canonical-text persistence only. The language
service's detector and configured translation models need their own verification;
a falsely labeled English response cannot be made accurate by this consumer.
