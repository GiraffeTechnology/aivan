# Stage 4 guided-relay implementation evidence

Status: implementation complete on the Stage 4 development branch; CTYun
deployment and mobile-channel production acceptance remain gated on PR review
and an approved deployment window.

## Delivered

- A fail-closed Channel Capability Registry:
  - Email and LINE: `auto_send`;
  - WeChat and Wangwang: `guided_relay`;
  - WhatsApp and unknown channels: `unsupported`.
- `GET /api/channels/capabilities` returns the canonical matrix.
- `GET /api/relay/outbox` returns only the authenticated tenant's approved
  guided-relay drafts and exposes copy-ready payloads.
- `POST /api/relay/{draft_id}/confirm` requires send authorization, an
  `Idempotency-Key`, and delivery evidence. It moves the draft from
  `approved_pending_send` to `sent`, persists one immutable receipt, and writes
  a `RELAY_DELIVERY_CONFIRMED` audit event.
- `POST /api/relay/inbound` accepts only relay-capable channels, requires a
  stable inbound identity, forces `source=relay`, and reuses the unified AIVAN
  inbound/Case/idempotency pipeline.
- The inbound participant remains the external sender. The authenticated bridge
  actor remains separate and cannot replace the WeChat/Wangwang participant.
- Additive, preview-first database migration for the relay receipt ledger and
  draft channel-account binding.

## Automated acceptance

`tests/test_stage4_relay.py` includes five consecutive WeChat guided-relay
approval-and-confirmation runs, plus tenant-isolation, unsupported-channel,
receipt-idempotency, inbound replay, account binding, and external-participant
assertions. `tests/test_stage4_migration.py` proves preview, additive apply, and
idempotent re-apply behavior.

These are deterministic local acceptance runs. They do not claim a live mobile
WeChat delivery.

## Production acceptance constraints

- Do not stop, rebind, or modify AIVAN server ports `443` or `8443`; they are
  reserved by existing SSH/mail services.
- Any CTYun path to a non-China IP must traverse the existing `abcdyi-sin`
  Singapore bridge.
- Inject channel credentials and API keys from the authorized secret store;
  never place them in the repository or test evidence.
- Run the Stage 4 migration only after a database backup.
- After cross-review and deployment, complete five consecutive real mobile
  WeChat/Relay round trips and retain redacted receipt, trace, Case binding, and
  audit-log evidence for each run.
