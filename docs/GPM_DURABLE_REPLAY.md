# Existing GPM durable replay

A committed quote-guidance request is read from the configured tenant-bound
packet provider before invoking the existing model again. A repeated key with
identical original business input and actor returns the stored analysis,
including its original model provenance and source trace. A different case,
quote, supplier, SKU, price, currency, quantity, margin, buyer/supplier totals,
GLTG reference, evidence, note or actor returns HTTP 409 before model execution.
A new transport correlation trace alone does not create a new decision.

Replay responses retain HTTP 201 for compatibility and use transport headers
`X-GPM-Replayed: true` and `X-GPM-Request-SHA256` to attest the same canonical
business request. The consumer verifies the request digest before accepting
an original source trace on a later transport attempt. The digest is not an
authentication credential; ordinary authenticated HTTP and tenant/actor/context
validation still apply. No stored trace, model output or approval is rewritten.

A missing packet permits the existing model call and durable create/readback.
An unavailable provider fails closed in production before a model call. Two
simultaneous requests without a committed packet may both reach the existing
model; the provider's atomic idempotency receipt decides one durable result.
A conflicting in-flight output is not silently accepted; retrying after the
commit reuses the stored result without a further model invocation.

Focused regressions use explicitly synthetic stored/model responses to prove
that replay does not execute the model, survives a new packet-store instance,
and rejects changed commercial/context input. This does not establish actual
model accuracy, live-model availability, deployment or full product acceptance.
Actual HTTP/provider tests separately preserve their configured provenance.
Human approval and commercial dispatch remain unchanged.
