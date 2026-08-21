#!/usr/bin/env python3
"""Preview or apply the ordered AIVAN schema migration set.

The default mode is read-only. Applying requires an immutable candidate SHA,
an approved authorization reference, and a verified backup reference. Reference
values are stored only as SHA-256 digests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from aivan.db.models import Base
from aivan.db.models.migration import SchemaMigrationRecord
from aivan.db.schema_validation import schema_issues
from scripts import (
    migrate_stage1_tenant_context as stage1,
    migrate_stage2_role_domain as stage2,
    migrate_stage4_relay as stage4,
    migrate_stage5a_event_correction as stage5a,
)


SCHEMA_VERSION = "2026.08.10-stage7b"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def plan(database_url: str, tenant_id: str) -> dict:
    return {
        "mode": "plan",
        "schema_version": SCHEMA_VERSION,
        "stages": {
            "stage1": stage1.plan(database_url),
            "stage2": stage2.plan(database_url),
            "stage4": stage4.plan(database_url),
            "stage5a": stage5a.plan(database_url),
        },
        "tenant_id_present": bool(tenant_id.strip()),
    }


def apply(
    database_url: str,
    *,
    tenant_id: str,
    candidate_sha: str,
    authorization_reference: str,
    backup_reference: str,
    bootstrap_empty: bool = False,
) -> dict:
    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("candidate SHA must be 40 lowercase hexadecimal characters")
    if not tenant_id.strip():
        raise ValueError("verified tenant id is required")
    if not authorization_reference.strip() or not backup_reference.strip():
        raise ValueError("authorization and verified backup references are required")
    engine = create_engine(database_url)
    try:
        existing_tables = set(inspect(engine).get_table_names())
        if not existing_tables:
            if not bootstrap_empty:
                raise RuntimeError("empty database requires explicit --bootstrap-empty")
            Base.metadata.create_all(engine)
            stage_results = {"bootstrap": "base_metadata_created"}
        else:
            stage_results = {
                "stage1": stage1.apply(database_url, tenant_id),
                "stage2": stage2.apply(database_url),
                "stage4": stage4.apply(database_url),
                "stage5a": stage5a.apply(database_url),
            }
            SchemaMigrationRecord.__table__.create(engine, checkfirst=True)
        issues = schema_issues(engine)
        if issues:
            raise RuntimeError(f"schema validation failed with {len(issues)} unresolved issue(s)")
        evidence_payload = json.dumps(stage_results, sort_keys=True, default=str)
        with Session(engine) as session:
            record = session.get(SchemaMigrationRecord, SCHEMA_VERSION)
            if record is None:
                record = SchemaMigrationRecord(
                    version=SCHEMA_VERSION,
                    candidate_sha=candidate_sha,
                    authorization_digest=_digest(authorization_reference.strip()),
                    backup_digest=_digest(backup_reference.strip()),
                    evidence_digest=_digest(evidence_payload),
                    applied_at=datetime.now(timezone.utc),
                )
                session.add(record)
            elif record.candidate_sha != candidate_sha:
                raise RuntimeError("schema version is already bound to a different candidate")
            session.commit()
        return {
            "mode": "applied",
            "schema_version": SCHEMA_VERSION,
            "candidate_sha": candidate_sha,
            "authorization_digest": _digest(authorization_reference.strip()),
            "backup_digest": _digest(backup_reference.strip()),
            "evidence_digest": _digest(evidence_payload),
            "schema_current": True,
        }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("AIVAN_DB_URL", ""))
    parser.add_argument("--tenant-id", default=os.environ.get("AIVAN_TENANT_ID", ""))
    parser.add_argument("--candidate-sha", default=os.environ.get("AIVAN_CANDIDATE_SHA", ""))
    parser.add_argument("--authorization-reference", default="")
    parser.add_argument("--backup-reference", default="")
    parser.add_argument("--bootstrap-empty", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or AIVAN_DB_URL is required")
    result = (
        apply(
            args.database_url,
            tenant_id=args.tenant_id,
            candidate_sha=args.candidate_sha,
            authorization_reference=args.authorization_reference,
            backup_reference=args.backup_reference,
            bootstrap_empty=args.bootstrap_empty,
        )
        if args.apply
        else plan(args.database_url, args.tenant_id)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    if not args.apply:
        print("No database changes made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
