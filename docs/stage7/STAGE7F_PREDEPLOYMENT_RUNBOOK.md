# Stage 7F production-predeployment runbook

Status: candidate procedure; **not production acceptance**
Target: CTYun AIVAN `/opt/giraffe/aivan`, `myaivan.service`, `127.0.0.1:8765`
Public route: `myaivan.com` through the existing `abcdyi-sin` bridge

## Non-negotiable safety boundary

- AIVAN ports `443` and `8443` are protected. They remain owned by the existing
  nginx and Stalwart services. Do not stop, restart, rebind, reuse, or modify
  either port or its owning service.
- CTYun must not connect directly to a non-China IP. Source transfer and every
  external dependency must use the approved `abcdyi-sin` path.
- Do not modify mail, MX, Stalwart configuration, or the AIVAN SNI route.
- No Email, LINE, WeChat, Wangwang, or other outbound business message may be
  sent without a separately recorded per-action authorization.
- Secrets are injected from the authorized host configuration store. Never put
  their values in a repository, task message, command output, log, or evidence.
- The UI deployment is executed and evidenced by the `MyAivan` task. It must use
  the exact merged candidate SHA supplied by the AIVAN task.

## Required inputs

1. A merged, full 40-character candidate SHA with green CI, CodeQL, dependency
   review, and Codex/Claude Code cross-review.
2. An approved change/authorization reference and an approved rollback owner.
3. A verified database-backup reference bound to the same change.
4. A production environment file created from
   `deploy/aivan.production.env.example`, present only on the target host.
5. A topology observation document created from
   `deploy/myaivan.predeployment.json.example`. It contains booleans and SHA-256
   digests only, never raw command output.
6. DNS/certificate/route readiness for `https://myaivan.com` on the existing
   Singapore TLS path. This must not be implemented by taking over AIVAN 443.

## Phase A — read-only discovery

Record SHA-256 digests of these observations without copying raw output into
the evidence file:

- target hostname/cloud profile, `/opt/giraffe/aivan`, branch and current SHA;
- `myaivan.service` unit identity, working directory, bind address and health;
- AIVAN listeners and owners for 443, 8443 and 8765;
- `aivan-bridge-tunnel.service`, local forwards and Singapore listener 18765;
- health through Singapore loopback 18765;
- database URL profile and schema preview;
- installed local model identity; it is observed, not installed or replaced;
- available disk/memory and the rollback owner.

Abort when 443/8443 ownership differs, the bridge is down, a required secret is
missing, CORS contains `*`, the database profile differs, or the candidate is
not immutable.

## Phase B — predeployment gate

Run on the prepared candidate checkout. The command is read-only except for
appending the local JSONL evidence file:

```text
python scripts/run_stage7f_predeployment.py \
  --candidate-commit <merged-40-char-sha> \
  --environment-file <host-only-production-env> \
  --topology-file <digest-only-topology-observation.json> \
  --output <append-only-evidence.jsonl>
```

The only passing evidence class is `production_predeployment`; the runner
hardcodes `production_acceptance=false`. A pass does not authorize deployment,
migration, service restart, DNS change, or a real-channel message.

## Phase C — backup and migration preview

1. Stop before mutation and reconfirm the authorization reference.
2. Create an atomic, permission-restricted backup of `data/aivan.db` and its
   SQLite sidecars if present. Record file metadata and SHA-256 in the protected
   operations evidence store; do not copy application rows into evidence.
3. Verify the backup by opening the copy read-only and running an integrity
   check. A file copy without verification is not a backup gate pass.
4. Run `scripts/run_aivan_migrations.py` without `--apply`. Review the plan and
   record only its digest.
5. Bind any later migration apply to the merged candidate SHA, authorization
   reference, and verified backup reference. Re-run the preview after apply;
   unresolved schema issues require rollback.

## Phase D — candidate deployment owned by MyAivan

The `MyAivan` task performs the authorized UI deployment only after it receives
the merged SHA. It must:

1. transfer a source/manifest package through the approved bridge, never by a
   direct CTYun GitHub connection;
2. verify candidate, lockfile, and package digests before activation;
3. prepare a new release directory and virtual environment without overwriting
   the current release or historical `.env` backups;
4. apply the approved migration only after the verified backup gate;
5. switch `myaivan.service` to the candidate with the shortest possible local
   interruption, without touching nginx, Stalwart, 443, or 8443;
6. verify `/health`, `/readyz`, protected `/metrics`, session bootstrap, role
   switch, case projection, audit export, and bridge health;
7. verify public `https://myaivan.com` on a real mobile device and record
   screenshots/receipts in the protected evidence store;
8. report the deployed full SHA and digest-only before/after evidence to the
   AIVAN task.

## Rollback trigger and procedure

Rollback immediately on migration failure, readiness failure, session/auth
regression, bridge failure, protected-port ownership change, unbounded error
rate, or candidate/digest mismatch.

1. Stop only `myaivan.service` if necessary; do not touch nginx, Stalwart, 443,
   or 8443.
2. Restore the previous service release target and host-only environment.
3. If the migration changed the database, restore the verified database backup
   using the approved rollback reference.
4. Start only `myaivan.service`; verify local health, Singapore bridge health,
   and the previous public route.
5. Record rollback digests and outcome. A successful rollback does not convert
   the failed candidate into accepted production evidence.

## Production acceptance remains separate

Stage 7F acceptance requires the same deployed SHA to pass the PRD's five
consecutive production rounds, real-device UI workflow, authorized channel
receipts/relay confirmations, monitoring/backup evidence, and all named
sign-offs. Missing or unauthorized channel tests remain explicitly unmet; they
are never skipped or converted into a pass.
