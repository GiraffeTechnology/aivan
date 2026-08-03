# Stage 1 unified request-context migration

Stage 1 adds an authenticated tenant stamp to `projects`, `inquiry_drafts`, and
`processed_inbound_events`. Existing rows must be assigned to a tenant verified
by the deployment operator; the migration never guesses from message content.

## Before deployment

1. Back up the AIVAN database and verify that the backup can be restored.
2. Confirm the owner tenant for all pre-Stage-1 rows. If one database contains
   more than one tenant, split/backfill it with an operator-reviewed SQL plan
   instead of using this single-tenant helper.
3. Stop writers or put the service in maintenance mode.
4. Preview without changing the database:

   `uv run python scripts/migrate_stage1_tenant_context.py --tenant-id <verified-tenant>`

5. Apply only after reviewing the plan:

   `uv run python scripts/migrate_stage1_tenant_context.py --tenant-id <verified-tenant> --apply`

6. Configure either:

   - `AIVAN_API_KEY` plus a deployment-bound `AIVAN_TENANT_ID`, or
   - `AIVAN_TENANT_API_KEYS` as a JSON object mapping tenant IDs to independent keys.

In production, absent authentication, absent tenant binding, invalid keys, body
role impersonation, and body/header tenant mismatches fail closed.

## Client contract

All business requests use `X-AIVAN-API-Key` (or Bearer compatibility),
`X-AIVAN-Tenant-ID`, and `X-AIVAN-Trace-ID`. Delivery/webhook clients should
also send `Idempotency-Key`. Trusted bridges provide role and channel identity
through `X-AIVAN-Role-Context`, `X-AIVAN-Actor-ID`, and
`X-AIVAN-Channel-Account-ID`; request-body identity is not authoritative in
production.

## Rollback

Stop the Stage 1 service and restore the pre-migration database backup before
deploying the previous application version. Do not drop tenant columns in place:
that would destroy the ownership data needed to investigate a failed rollout.
