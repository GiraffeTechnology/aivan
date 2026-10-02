# Historical Stage 5 Asset Inventory

Reconciled: 2026-10-02. This record preserves earlier engineering organization without treating it as the current product scope or a mandatory stage chain.

## Useful areas retained

- Event impact preview and immutable correction, with tenant, role and idempotency checks.
- Shared case, conversation, participant, draft, approval and audit APIs.
- Channel adapters and guided-relay records with truthful approval/delivery distinctions.
- Web session/workbench, audit and supporting operations views.

The original tracker marked several areas incomplete. This cleanup does not relabel them passed. Current results must be verified at the selected candidate.

## Reconciled scope

MyAivan uses the shared Aivan business model on its independent `myaivan-web` release branch, which never merges into `main`. Its first UI is Welcome/Start Working and conversation/review/input, usable files/images, copy/manual IM, explicit configured-email confirmation/fallback and Markdown backup.

All first-web IM channels, including LINE and WhatsApp, use manual copy/send/confirmation. Existing automatic adapters remain preserved assets, not a requirement or authorization for that iteration. Attachment placeholders do not satisfy required file/image input. Broader correction and operational surfaces may remain useful without becoming hidden UI prerequisites.

Use [current acceptance](../ACCEPTANCE_CRITERIA.md), including the original five-run UI tests and later DB/English requirements. Preserve expanded code by exact revision in [the inventory](../SCOPE_PRESERVATION_INVENTORY.md); do not delete it or infer that every complex feature is unauthorized.
