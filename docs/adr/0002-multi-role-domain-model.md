# ADR 0002: Multi-role identity and shared case model

Status: Accepted for Stage 2 implementation

## Context

The legacy event boundary carries `role_context` and `mode` strings. Those
values route buyer, supplier, and operator messages, but they do not identify
the actor, grant capabilities, constrain the participant thread, or record the
authorization basis for a transition.

## Decision

AIVAN uses four independent identity dimensions:

1. `actor_id`: authenticated person or service identity.
2. `business_role`: one canonical role from buyer, supplier, sales,
   procurement, follow_up, qc, logistics, admin, approver, or auditor.
3. `conversation_role`: the case participant thread used by the action.
4. `execution_mode`: auto, command, approval, update, or audit.

Legacy B/M aliases are accepted only at an ingress adapter and immediately
normalized. Capability checks use `business_role`; neither message text nor a
request-body role grants authority. Case transitions use an explicit transition
table and emit before/after, actor, role, trace, authorization basis, and any
rejection reason.

The existing `Project` identifier remains the compatibility case identifier
during migration. New Participant, Conversation, Message, Approval, and Audit
records reference that identifier as `case_id`; adapters may continue exposing
`project_id` until downstream consumers migrate.

## Consequences

- Production-sensitive actions require trusted actor and role headers.
- Buyer/supplier routing remains backward compatible at the boundary.
- Unauthorized approvals, sends, supplier selection, and delivery commitments
  fail closed with typed errors and rejected-action audit records.
- Database changes are additive and require an operator-reviewed backfill.
