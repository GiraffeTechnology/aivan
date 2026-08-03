# Stage 2 multi-role Case domain migration

This additive migration introduces the canonical `Case` domain while retaining
`projects.project_id` as the compatibility Case identifier. It creates role-specific
conversation, participant, message, approval, and audit tables and adds trace/actor
columns to existing projects, drafts, and execution events.

## Before applying

1. Stop AIVAN writers or place them in maintenance mode.
2. Take and verify a database backup.
3. Confirm Stage 1 migration and application release are installed.
4. Run the preview command against the exact target URL:

   ```bash
   python scripts/migrate_stage2_role_domain.py --database-url "$AIVAN_DB_URL"
   ```

The preview performs no writes. Review every `create` and `add` line.

## Apply

```bash
python scripts/migrate_stage2_role_domain.py \
  --database-url "$AIVAN_DB_URL" \
  --apply
```

The operation is idempotent. Re-running it reports existing tables/columns and
does not delete or overwrite business records. Existing execution events receive
the explicit `legacy` tenant default; JSON audit snapshots may be null for legacy
rows and are populated for new Stage 2 events.

## Verification

- Confirm tables: `case_conversations`, `case_participants`, `case_messages`,
  `approvals`, `audit_logs`.
- Confirm `projects.case_state` and `projects.source_trace_id`.
- Confirm actor, role, trace, authorization, before/after, and rejection columns
  on `execution_events`.
- Run the Stage 2 role/domain/approval tests before restoring traffic.

## Rollback

Application rollback is safe because all changes are additive and compatibility
fields remain. Do not drop Stage 2 tables or columns as an automated rollback:
they contain audit and authorization evidence. If application rollback is needed,
deploy the previous binary, preserve the added data, and restore from the verified
backup only under an approved data-recovery procedure.
