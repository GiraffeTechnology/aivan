# Evidence-bound buyer option selection

Aivan presents up to three actual, distinct available supplier quotations; it
does not manufacture options to reach three. Existing current-valid-revision
deduplication, source quotation references and the currency/unit comparability
checks remain in force. If fastest and lowest-cost identify different suppliers,
another actual candidate may still fill the remaining slot. Zero, one and two
available candidates remain valid counts and are not padded.

Comparable price sorting uses the quoted numeric value, including an explicit
zero if admitted by the existing quote contract. It does not replace zero by an
invented high price through truthiness. Missing, negative and non-finite prices
are excluded before current-valid-revision selection and monetary conversion,
not substituted. An invalid follow-up cannot replace an available valid quote.
Explicit zero remains admitted; this does not authorize free orders or alter
commercial approval, quote calculations,
margins, taxes, quantity/terms or currency conversion.

When the lowest-cost quote is already the fastest option, another comparable
quote is an alternative, not a second lowest-cost or evidence-free best-value
claim. Existing provider lead-time quantiles and deadline risks remain separate
from these presentation labels; Aivan does not recalculate the GLTG model.

Overall `risk_level` remains unknown unless there is an appropriate explicit
overall-risk source. An empty parsed risk list is not proof of low risk, and
the presence of a note is not proof of medium risk. Parsed notes are exposed
as parsed notes, not verified supplier facts. The existing separately named
GLTG deadline risk and feasibility fields are retained unchanged.

This source change does not claim real-service acceptance. Check actual counts,
distinct-source selection, comparable numeric zero, currency/unit mismatch,
current quote revisions, evidence labels and unchanged provider deadline data
in the receiving test/integration environment. Human approval, rejected draft
invalidation, private DB persistence and channel delivery remain separate actions.
