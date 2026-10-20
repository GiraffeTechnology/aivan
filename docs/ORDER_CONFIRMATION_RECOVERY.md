# Order confirmation: unknown write outcomes

Human-confirmed quotation and purchase-order writes use the existing tenant-bound
provider API and stable per-option operation keys. This consumer adds no order
system, mapping table, schema or external-send action. Separate quote and order
writes are not a distributed transaction.

A transport failure, redirect, non-contract response or malformed successful
acknowledgement may occur after a provider commit. Aivan queries the existing
`GET /api/data/write-results/{operation}/{key}` once instead of blindly issuing
another POST or creating a different operation key. An object without the actual
quote/order primary key is not accepted as a successful acknowledgement.

Recovery requires the provider's committed receipt, record and matching target
ID for supplier_quotes or purchase_orders. Supplied tenant/idempotency-key
echoes must agree with the authenticated request. They are not newly required
response fields: compatible adapters preserve tenant/key scope through the
existing authenticated receipt endpoint. Missing, mismatched, unavailable or
malformed recovery evidence remains `ORDER_CONFIRMATION_INDETERMINATE_COMMIT`
for the affected operation. No raw error body or connection details are returned.

After both writes return records, direct quote/order and transaction-graph
readback are still required before success. A failed read at this point returns
`ORDER_CONFIRMATION_INDETERMINATE_COMMIT:readback`, not an assertion that no
provider writes happened. Successful but inconsistent business readback retains
its existing mismatch error; it does not become success. A later explicit retry
of the same selected option uses the same existing provider keys and readback.
Do not regenerate a commercial key or automatically resend a business message
merely because a read failed. Existing definite POST auth denial, input error
and idempotency conflict remain separately distinguishable.

This is not proof of real database durability. Receiving verification covers
acknowledgement loss followed by recovery timeout, malformed200 with recoverable
receipt, mismatched receipt/tenant/key/target, redirect and final readback loss;
then recovery/replay without duplicate quotes/orders. Use actual provider and
selected database evidence for restart/integration acceptance. No database type
is inferred from a unit transport fixture, and no production write is run by
the source change itself.
