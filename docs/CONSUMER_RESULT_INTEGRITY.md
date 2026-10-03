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
## Inbound execution ownership

An inbound identity is reserved in the existing unique database ledger before
workflow side effects. A prior absent read is not authorization to execute:
concurrent insert conflicts read and replay the completed receipt, or return
`409 INBOUND_OUTCOME_UNCONFIRMED` with the request trace ID if processing has
not been confirmed complete. A completed retry does not call translation again.
Relay audit replay classification follows this actual receipt outcome.

The claim survives intermediate workflow commits and process loss. It does not
expire into automatic re-execution, because business effects may already have
committed. An incomplete claim requires checking the persisted outcome; the
error does not assert that the workflow rolled back or that retrying can repeat
the action. This is not a claim of distributed atomicity. Unit tests use
controlled SQLite transaction interleavings and do not certify MySQL behavior
or full live-service workflow acceptance.
