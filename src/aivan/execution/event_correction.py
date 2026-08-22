"""Stage 5 impact preview and append-only event correction service."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aivan.db.models.execution import EventReversalRecord, ExecutionEventRecord
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.repositories.reversal_repo import (
    EventReversalRepository,
    reversal_idempotency_key,
)
from aivan.domain.roles import ActorIdentity


class EventCorrectionError(RuntimeError):
    pass


class UnsafeAutomaticReversal(EventCorrectionError):
    def __init__(self, impact: dict):
        super().__init__("Event cannot be automatically reversed")
        self.impact = impact


class ReversalConflict(EventCorrectionError):
    pass


def _canonical_digest(value: dict) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def event_payload_digest(event: ExecutionEventRecord) -> str:
    return event.payload_digest or _canonical_digest(
        {
            "event_type": event.event_type,
            "summary": event.summary,
            "payload": event.payload_json or {},
            "before": event.before_json or {},
            "after": event.after_json or {},
        }
    )


def _event_ref(event: ExecutionEventRecord) -> dict:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "derived_from_event_id": event.derived_from_event_id,
        "payload_digest": event_payload_digest(event),
        "correction_status": event.correction_status,
        "created_at": str(event.created_at),
    }


def _reversal_ref(record: EventReversalRecord | None) -> dict | None:
    if record is None:
        return None
    return {
        "reversal_id": record.reversal_id,
        "source_event_id": record.source_event_id,
        "correction_event_id": record.correction_event_id,
        "status": record.status,
        "actor_id": record.actor_id,
        "actor_role": record.actor_role,
        "source_trace_id": record.source_trace_id,
        "reason": record.reason,
        "source_payload_digest": record.source_payload_digest,
        "impact_digest": record.impact_digest,
        "created_at": str(record.created_at),
    }


def build_event_impact(
    db: Session, event: ExecutionEventRecord, *, tenant_id: str
) -> dict:
    events = ExecutionEventRepository(db)
    reversals = EventReversalRepository(db)
    project = ProjectRepository(db).get(event.project_id, tenant_id=tenant_id)
    downstream = events.list_after(event, tenant_id=tenant_id)
    derived = events.list_derived(event.event_id, tenant_id=tenant_id)
    existing_reversal = reversals.get_for_source(event.event_id, tenant_id=tenant_id)
    before = event.before_json or {}
    after = event.after_json or {}
    blockers: list[str] = []
    warnings: list[str] = []
    reversible_field = ""
    current_value = None
    expected_after = None

    if existing_reversal is not None:
        blockers.append("event_already_corrected")
    if event.derived_from_event_id or event.correction_status:
        blockers.append("correction_events_cannot_be_reversed")
    if project is None:
        blockers.append("case_not_found")
    elif "case_state" in before and "case_state" in after:
        reversible_field = "case_state"
        current_value = project.case_state
        expected_after = after["case_state"]
    elif "strategy" in before and "strategy" in after:
        reversible_field = "strategy"
        current_value = (project.requirement_json or {}).get("strategy")
        expected_after = after["strategy"]
    else:
        blockers.append("no_supported_materialized_state")

    if reversible_field and current_value != expected_after:
        blockers.append("materialized_state_diverged")
    if reversible_field:
        later_mutations = [
            item.event_id
            for item in downstream
            if reversible_field in (item.before_json or {})
            or reversible_field in (item.after_json or {})
        ]
        if later_mutations:
            blockers.append("later_mutation_exists")
            warnings.append(
                "Later events mutate the same field: " + ", ".join(later_mutations)
            )
    non_correction_derived = [
        item for item in derived if not item.correction_status
    ]
    if non_correction_derived:
        blockers.append("derived_events_exist")
    if downstream:
        warnings.append(
            f"{len(downstream)} later event(s) in the same Case require review."
        )

    affected = {
        "case_id": event.project_id,
        "materialized_field": reversible_field,
        "current_value": current_value,
        "expected_after": expected_after,
        "restore_value": before.get(reversible_field) if reversible_field else None,
        "downstream_event_count": len(downstream),
        "derived_event_count": len(non_correction_derived),
    }
    digest_input = {
        "tenant_id": tenant_id,
        "source_event": _event_ref(event),
        "before": before,
        "after": after,
        "affected": affected,
        "blockers": blockers,
        "downstream": [_event_ref(item) for item in downstream],
        "derived": [_event_ref(item) for item in derived],
    }
    return {
        "tenant_id": tenant_id,
        "source_event": {
            **_event_ref(event),
            "case_id": event.project_id,
            "before": before,
            "after": after,
        },
        "affected": affected,
        "downstream_events": [_event_ref(item) for item in downstream],
        "derived_events": [_event_ref(item) for item in derived],
        "automatic_reverse_allowed": not blockers,
        "compensation_required": bool(blockers),
        "blockers": blockers,
        "warnings": warnings,
        "existing_reversal": _reversal_ref(existing_reversal),
        "impact_digest": _canonical_digest(digest_input),
    }


@dataclass
class ReversalResult:
    record: EventReversalRecord
    correction_event: ExecutionEventRecord | None
    idempotent_replay: bool
    impact: dict


def reverse_event(
    db: Session,
    event: ExecutionEventRecord,
    *,
    tenant_id: str,
    supplied_idempotency_key: str,
    identity: ActorIdentity,
    source_trace_id: str,
    reason: str,
    compensation_only: bool = False,
) -> ReversalResult:
    impact = build_event_impact(db, event, tenant_id=tenant_id)
    reversals = EventReversalRepository(db)
    stored_key = reversal_idempotency_key(tenant_id, supplied_idempotency_key)
    by_key = reversals.get_for_idempotency_key(stored_key, tenant_id=tenant_id)
    if by_key is not None and by_key.source_event_id != event.event_id:
        raise ReversalConflict("Idempotency key was already used for another event")
    existing = reversals.get_for_source(event.event_id, tenant_id=tenant_id)
    if existing is not None:
        correction = (
            ExecutionEventRepository(db).get(
                existing.correction_event_id, tenant_id=tenant_id
            )
            if existing.correction_event_id
            else None
        )
        return ReversalResult(existing, correction, True, impact)
    if not impact["automatic_reverse_allowed"] and not compensation_only:
        raise UnsafeAutomaticReversal(impact)

    status = "compensation_required" if compensation_only else "applied"
    record, created = reversals.create_or_get(
        tenant_id=tenant_id,
        case_id=event.project_id,
        source_event_id=event.event_id,
        idempotency_key=stored_key,
        status=status,
        actor_id=identity.actor_id,
        actor_role=identity.business_role.value,
        source_trace_id=source_trace_id,
        reason=reason,
        source_payload_digest=event_payload_digest(event),
        impact_digest=impact["impact_digest"],
        before_ref_json=event.before_json or {},
        after_ref_json=event.after_json or {},
    )
    if not created:
        if record.source_event_id != event.event_id:
            raise ReversalConflict("Idempotency key was already used for another event")
        correction = (
            ExecutionEventRepository(db).get(
                record.correction_event_id, tenant_id=tenant_id
            )
            if record.correction_event_id
            else None
        )
        return ReversalResult(record, correction, True, impact)

    project = ProjectRepository(db).get(event.project_id, tenant_id=tenant_id)
    correction_before = event.after_json or {}
    correction_after = event.after_json or {}
    event_type = "EVENT_COMPENSATION_REQUIRED"
    summary = f"Compensation required for {event.event_id}: {reason}"
    if status == "applied":
        field = impact["affected"]["materialized_field"]
        restore_value = impact["affected"]["restore_value"]
        if field == "case_state":
            project.case_state = restore_value
        elif field == "strategy":
            requirement = dict(project.requirement_json or {})
            requirement["strategy"] = restore_value
            project.requirement_json = requirement
        correction_after = event.before_json or {}
        event_type = "EVENT_REVERSED"
        summary = f"Reversed {event.event_id}: {reason}"

    correction = ExecutionEventRepository(db).append(
        event.project_id,
        event_type,
        summary,
        payload={
            "reversal_id": record.reversal_id,
            "source_event_id": event.event_id,
            "source_payload_digest": record.source_payload_digest,
            "impact_digest": record.impact_digest,
            "reason": reason,
        },
        actor="event_correction",
        tenant_id=tenant_id,
        source_trace_id=source_trace_id,
        actor_id=identity.actor_id,
        actor_role=identity.business_role.value,
        conversation_role=identity.conversation_role.value,
        authorization_basis=identity.authorization_basis,
        before=correction_before,
        after=correction_after,
        derived_from_event_id=event.event_id,
        correction_status=status,
    )
    record.correction_event_id = correction.event_id
    db.flush()
    return ReversalResult(record, correction, False, impact)


def serialize_reversal_result(result: ReversalResult) -> dict:
    return {
        "status": result.record.status,
        "idempotent_replay": result.idempotent_replay,
        "reversal": _reversal_ref(result.record),
        "correction_event": (
            _event_ref(result.correction_event) if result.correction_event else None
        ),
        "impact": result.impact,
    }
