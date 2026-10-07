# Requirement clarification

The MyAivan web branch exposes authenticated, case-scoped human corrections.
This extends inquiry/quotation/order confirmation; it does not send a message or
confirm an order on the user's behalf.

1. `GET /api/workbench/cases/{case_id}/requirement` returns `requirement` and
   `requirement_sha256` from the database.
2. `PATCH /api/workbench/cases/{case_id}/requirement` requires the same authenticated
   session/API principal, CSRF for cookie sessions, and an `Idempotency-Key`.
   Example JSON:

   ```json
   {
     "expected_requirement_sha256": "<the current GET response hash>",
     "fields": {
       "fabric_material": "cotton",
       "color": "white",
       "size_ratio": "S/M/L/XL 20/40/30/10",
       "packaging": "Individually bagged"
     }
   }
   ```

Only business requirement fields are editable; callers cannot replace audit,
provider references, roles, missing-field flags or confirmation state. Buyers
must be bound to the case. Sales, procurement, approver and administrator roles
use the existing workbench access policy.

The shared language service validates stored fields and dynamically normalizes
non-English input before processing. An unavailable or uncertain language result
fails closed. Original text is represented by its hash, not an original-language
business field.

A changed material requirement supersedes unsent drafts, removes the selected
quote, retains historical approval evidence and returns the case to supplier
review. GLTG and the selected private-data provider are called through their
existing APIs; revised case/RFQ requirements are read back and compared exactly.
A subsequent supplier response produces a new quotation for human review.
Already confirmed orders require an amendment workflow and are not silently
rewritten by this endpoint. Optional missing fields such as GSM do not block an
otherwise supported confirmation; explicit material gaps do.

The same idempotency key and body replay the stored correction. A stale snapshot
or conflicting retry returns 409. Provider response loss is reconciled using the
same operation keys and recorded requirement/analysis instead of inventing a new
snapshot. Local SQL is the configured durable store in explicitly offline mode;
that mode does not claim remote-provider acceptance.
