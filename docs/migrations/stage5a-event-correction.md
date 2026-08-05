# Stage 5A event-correction migration

This additive migration introduces event lineage and immutable correction
evidence:

- `execution_events.derived_from_event_id` links corrective/derived events;
- `execution_events.payload_digest` protects the recorded payload snapshot;
- `execution_events.correction_status` distinguishes applied reversal from
  compensation-required evidence;
- `event_reversals` stores one tenant-scoped, idempotent correction decision per
  source event.

Preview after taking a database backup:

```bash
uv run python scripts/migrate_stage5a_event_correction.py --database-url "$AIVAN_DB_URL"
```

Apply only in an approved maintenance window:

```bash
uv run python scripts/migrate_stage5a_event_correction.py --database-url "$AIVAN_DB_URL" --apply
```

The migration does not delete or rewrite source-event business fields. It only
adds schema and backfills missing payload digests. Re-running it is safe. A
rollback restores the pre-migration database backup; do not drop correction
evidence from a live database.
