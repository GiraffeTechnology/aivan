# Stage 4 guided-relay migration

Stage 4 adds the `relay_receipts` delivery-evidence table and the
`inquiry_drafts.channel_account_id` binding. The migration is additive: it does
not remove tables, columns, indexes, or rows.

Before deployment, back up the target database and preview the plan:

```bash
uv run python scripts/migrate_stage4_relay.py --database-url "$AIVAN_DB_URL"
```

After reviewing the plan, apply it during an approved maintenance window:

```bash
uv run python scripts/migrate_stage4_relay.py --database-url "$AIVAN_DB_URL" --apply
```

Run the same command again in preview mode. Both the table and column must show
`already_exists`. Start the new application only after this verification.

Rollback is restore-based. Stop the AIVAN application and restore the
pre-migration database backup. Do not drop the receipt ledger or column from a
live database: they contain audit evidence and older application versions
ignore them safely.
