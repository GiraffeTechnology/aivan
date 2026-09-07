# GPM Persistence Adapter Contract v1

Status: AIVAN G2-A consumer boundary. This document does not claim that a real
giraffe-db API, SDK, schema, migration, or Postgres deployment implements the
contract. Production remains fail-closed until the corresponding giraffe-db
stage is independently accepted and proven end to end.

## Identity and authentication

- Contract version: `gpm.persistence.v1`.
- Every adapter operation requires service authentication. A configured
  `GIRAFFE_DB_BASE_URL` without `GIRAFFE_DB_SERVICE_AUTH_SECRET` is unavailable,
  not an authenticated development fallback.
- Every packet operation requires an authenticated tenant. Tenant identity is
  carried separately from the body, and a body tenant may only equal that
  authenticated tenant.
- Every response must return the same tenant. Missing or mismatched tenant
  evidence fails closed.
- Tenant and packet identifiers are encoded as individual transport path
  segments; authenticated identifiers cannot change endpoint routing.
- Approval and rejection operator identity, role, authorization basis,
  idempotency key, and correlation ID come from authenticated request context.
  Request bodies cannot supply or override those facts.

The current HTTP adapter uses these header names as its transport mapping:
`X-Service-Auth`, `X-Service-Tenant-ID`, `X-GPM-Contract-Version`, and
`X-AIVAN-Correlation-ID`. Other provider implementations may use another
transport while preserving the same semantic contract.

## Atomic decision command

An approval or rejection is one adapter operation. Its command contains:

- packet and tenant identifiers;
- decision (`approved` or `rejected`) and expected status (`pending`);
- authenticated operator identifier and role;
- authorization basis, idempotency key, and correlation ID;
- optional non-identity notes; and
- contract version.

The operation succeeds only when its response proves, in one committed
transaction, all of the following:

- response packet and tenant equal the requested packet and authenticated tenant;
- requested decision and authenticated operator/role/authorization basis were applied;
- the same idempotency key was committed;
- `transaction_status=committed`;
- audit and lineage records were committed;
- `contract_version=gpm.persistence.v1`; and
- `dispatched=false`.

Legacy split status-update and audit-write operations are disabled for this
decision path. Missing proof, version drift, cross-tenant data, or an ambiguous
response is an error, never success.

## Idempotency and concurrency

The adapter is authoritative for production transaction isolation and durable
idempotency. Repeating the same tenant/idempotency/packet/decision tuple may
return its original committed receipt. Reusing a tenant/idempotency key for a
different packet or decision must fail. AIVAN serializes local compatibility
decisions only for deterministic tests; that memory behavior is not production
persistence and cannot establish real database support.

## Errors, logs, and fallback

Consumer-visible adapter errors expose only a stable error code and correlation
ID. Raw URLs, response bodies, credentials, stack traces, or remote exception
messages are not included. Production never falls back to memory, mock, stub,
or synthetic persistence. External unavailability leaves the operation
uncommitted and undispatched.

## Deferred acceptance

G2-A validates only the provider-neutral AIVAN consumer boundary. Real API/SDK
compatibility, schema/migration ownership, Postgres concurrency, durable replay
across processes/restarts, and live end-to-end evidence remain blocked on the
independent giraffe-db stage. No database files or migration definitions are
changed by G2-A.
