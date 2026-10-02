# GPM Persistence Adapter Contract v1

Reconciled: 2026-10-02. This is the existing Aivan consumer contract, not a mandatory independent product stage or a claim that a particular provider is deployed. A compatible private-domain DB may replace giraffe-db. Verify the real selected API, durable decision, isolation and recovery semantics using the designated simulated databases when accepting the integration.

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
messages are not included. Business operations never substitute memory, mock or stub responses for a committed DB result. A real DB populated with a designated simulated dataset is valid; that dataset does not make its persistence fake. External unavailability leaves the operation
uncommitted and undispatched.

## Provider acceptance and language

Verify real API compatibility, durable replay across processes/restarts, tenant isolation, concurrent/idempotent decisions and actual end-to-end readback for the chosen provider. Do not require a separate named giraffe-db stage, a fixed Postgres instance or production-customer data when another compatible provider satisfies the contract.

The DB is the history/process system of record. Except enterprise/user profile information, stored textual content is standard English. Non-English inputs are translated dynamically before workflow; notes, audit and metadata are not exceptions. This document changes no database files, migrations, runtime code or deployment configuration.
