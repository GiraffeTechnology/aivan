# Stage 7B–7E myAIVAN candidate tracker

Status date: 2026-08-20  
Status: **code candidate; not merged, deployed, or production accepted**

## Delivered in the candidate

- Trusted UI login exchanges the API credential for an HMAC-signed HttpOnly
  session. Unsafe UI requests require a separate CSRF token. JavaScript never
  stores the API credential.
- Server-configured actor identity and allowed roles control role switching;
  each role receives a restricted case projection.
- Workbench bootstrap, health, paginated case list, aggregate case detail and
  Markdown/JSON audit exports are tenant-scoped.
- Message evidence stores a versioned content reference and SHA-256 digest,
  never raw provider output.
- The responsive workbench exposes inquiry, approval, guided relay,
  correction/reversal, receipt, audit export and dependency-health surfaces.
  Attachments are deliberately fail-closed as metadata-only placeholders.
- The Core database profile is fixed to the existing durable
  `sqlite:///./data/aivan.db`; GiraffeDB/MySQL remains a separate integration
  service. Production startup validates the schema without creating tables. A
  preview-first migration orchestrator requires a frozen 40-character
  candidate SHA plus authorization and verified-backup references, stored only
  as digests.
- `/readyz`, protected Prometheus metrics, browser security headers, expanded
  type checks and Python/JavaScript CodeQL are included.
- A fail-closed Stage 7F predeployment runner validates the immutable SHA,
  production configuration shape, protected-port observations, Singapore
  bridge evidence, dependency locks and current schema. It records no secret
  values and is structurally incapable of issuing production acceptance.

## Reproducible candidate evidence

- Full regression: 797 passed, 2 skipped.
- Coverage: 81.52%; enforced floor: 75%.
- Ruff: passed.
- Mypy: passed for 12 safety-boundary modules.
- Bandit high-severity scan: passed.
- Mobile browser walkthrough: 390 × 844 viewport; session recovery, role
  switch, inquiry creation, case projection, digest-only evidence and export
  were exercised. This walkthrough is preflight, not production acceptance.

## Read-only production topology audit

- CTYun AIVAN already runs `myaivan.service` from the fixed
  `/opt/giraffe/aivan` directory on `127.0.0.1:8765`.
- The deployed service is the older `0.2.0` candidate and has `/health` but no
  `/readyz`.
- AIVAN listeners `443` and `8443` remain owned by the existing nginx
  SNI/mail path. They were not stopped, rebound, proxied, restarted or changed.
- The approved existing route is AIVAN nginx port 80 → myAIVAN 8765 → reverse
  tunnel → `abcdyi-sin` loopback 18765. On 2026-08-20 the restrictive
  `authorized_keys` bridge entry was repaired from an invalid `permitlisten`
  syntax using its timestamped backup. SSH configuration validation passed,
  the AIVAN tunnel returned to `active/running`, loopback 18765 resumed
  listening, and bridge health reported AIVAN `0.2.0`.
- The production repository is on branch `myaivan-web` at
  `b8def41adb54533f311e569b358a93d22ed6e565`; only historical `.env` backup
  files are untracked. Secret values were not read or copied.
- The application database is the fixed local `data/aivan.db`; GiraffeDB integration
  configuration is injected separately. Backup and migration have not run.

## Remaining gates before myaivan.com can be claimed deployed

1. Merge the frozen candidate after GitHub CI, CodeQL and the required
   Codex/Claude Code cross-review.
2. Resolve the public-domain gap. `myaivan.com` currently points at AIVAN,
   while AIVAN 443 intentionally routes only the approved existing SNI/mail
   traffic. HTTP redirects users to the separate `www.myaivan.cn:9443` entry;
   that is not direct `https://myaivan.com` delivery.
3. Keep AIVAN 443/8443 unchanged. The safe design is to terminate
   `myaivan.com` TLS on the existing `abcdyi-sin` 443 multiplexer/nginx path,
   then reuse the existing reverse bridge to AIVAN port 80/8765. This requires
   authorized DNS, certificate and Singapore nginx changes, not an AIVAN port
   change.
4. Record a verified database backup, preview and apply the migration bound to
   the merged candidate, then re-preview to prove schema convergence.
5. Update production configuration with the candidate SHA, exact CORS origin,
   trusted UI identity/session settings and existing bridge policy through the
   authorized configuration store. Do not copy secret values into evidence.
6. Perform a rollback drill and capture before/after port, health, readiness,
   bridge, metrics and log digests.
7. Run the required real-device acceptance against the same candidate. Missing
   channel receipts or required sign-offs remain failed/unmet; they are never
   silently skipped.

The exact predeployment, backup, migration-preview, MyAivan handoff and rollback
sequence is in `docs/stage7/STAGE7F_PREDEPLOYMENT_RUNBOOK.md`.

## Explicitly not complete

- separately paginated conversations/messages/participants/approvals/audit
  collections;
- object-storage attachment upload, malware/type/size checks and lifecycle;
- full downstream correction invalidation and compensation drafts;
- real Email/LINE receipts and real WeChat/Wangwang relay acceptance;
- SBOM/provenance/signing, alert/capacity and backup-restore evidence;
- GitHub control-plane sign-off and Stage 7F production sign-offs.
