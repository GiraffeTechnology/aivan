# Stage 5 delivery tracker

Stage 5 is intentionally split into independently reviewable PRs. PR #36 is a
reference only: its independent `web_*` Case, draft, and audit state machines
must not be merged into the shared Core.

## Stage 5A — Core event correction

- `GET /api/events/{event_id}/impact`
- `POST /api/events/{event_id}/reverse`
- tenant-scoped lineage, payload digest, idempotent reversal ledger
- append-only correction/compensation evidence; no physical history deletion

## Stage 5B — MyAIVAN Core API

- expose current Core Project/Case/Conversation/Participant/Draft/Approval/Audit
  models to the workbench
- migrate useful PR #36 behavior without importing `web_*` business tables or
  its independent draft status machine
- keep uploads in a separate, least-privilege boundary

## Stage 5C — unified delivery adapters

- Email and LINE auto-send through Core approval, receipt, and audit semantics
- WeChat/Wangwang continue through guided relay
- WhatsApp remains fail-closed unsupported

## Stage 5D — MyAIVAN UI

- role, approver, delivery mode, dependency error, relay card, impact preview,
  correction action, receipt, and audit timeline
- the browser stores no channel password, private key, or API token

## Carried acceptance items

Claude Code found no blocking defect in PR #56. The following operational
evidence remains deliberately unclaimed and is carried into Stage 5/6:

- current-main mobile WeChat/Relay five-run production evidence;
- transfer-card UI and attachment placeholder behavior;
- CTYun deployment evidence using the existing `abcdyi-sin` bridge for every
  non-China destination;
- AIVAN ports 443/8443 remain reserved and must not be modified.
