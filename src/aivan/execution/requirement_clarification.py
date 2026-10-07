"""Human-authenticated requirement corrections over existing workflow APIs."""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError

from aivan.agents.requirement_agent import _detect_missing_fields
from aivan.db.models.domain import AuditLogRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.domain.roles import BusinessRole
from aivan.integrations.language_skill_client import LanguageSkillClient
from aivan.integrations.language_skill import source_digest
from aivan.schemas.requirement import BuyerRequirement

EDITABLE_FIELDS = {
    'category', 'product_type', 'quantity', 'quantity_unit', 'fabric_material', 'gsm', 'color',
    'size_ratio', 'packaging', 'destination', 'target_unit_price', 'target_currency',
    'delivery_deadline_iso', 'delivery_days', 'incoterms', 'logistics_preference', 'notes',
}
MATERIAL_FIELDS = EDITABLE_FIELDS - {'notes'}
CONFIRMATION_MATERIAL_FIELDS = MATERIAL_FIELDS - {'gsm', 'target_unit_price', 'target_currency', 'logistics_preference', 'incoterms'}


def snapshot(requirement):
    return BuyerRequirement.model_validate(requirement or {}).model_dump()


def requirement_hash(requirement):
    return source_digest(json.dumps(snapshot(requirement), sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False))


def unresolved_material_fields(requirement):
    missing = set()
    for item in (requirement or {}).get('missing_fields', []):
        name = item.get('field_name') if isinstance(item, dict) else item
        if name in CONFIRMATION_MATERIAL_FIELDS:
            missing.add(name)
    return sorted(missing)


def _validate_english(client, fields):
    result = client._request('POST', '/api/language/canonical-db/validate', json={
        'repository': 'aivan', 'table_name': 'requirements', 'record': fields,
        'policy': 'standard_english_canonical_db_v1'})
    if not result.ok or not isinstance(result.data, dict):
        raise HTTPException(503, detail={'error': 'REQUIREMENT_LANGUAGE_VALIDATION_UNAVAILABLE'})
    return result.data


def normalize_fields(fields):
    """Validate first so machine-shaped ratios/units are never mistranslated."""
    client = LanguageSkillClient()
    checked = _validate_english(client, fields)
    normalized = dict(fields)
    if checked.get('valid') is True and checked.get('violations') == []:
        return normalized
    violations = checked.get('violations')
    if not isinstance(violations, list) or not violations:
        raise HTTPException(503, detail={'error': 'REQUIREMENT_LANGUAGE_VALIDATION_UNAVAILABLE'})
    keys = {str(item.get('field', '')).removeprefix('requirements.') for item in violations if isinstance(item, dict)}
    if not keys or any(key not in fields or not isinstance(fields[key], str) for key in keys):
        raise HTTPException(422, detail={'error': 'REQUIREMENT_LANGUAGE_NORMALIZATION_REQUIRED'})
    for key in keys:
        result = client.normalize(source_text=fields[key], domain_hint='trade_requirement')
        if not result.ok or not isinstance(result.data, dict):
            raise HTTPException(503, detail={'error': 'REQUIREMENT_LANGUAGE_NORMALIZATION_REQUIRED'})
        normalized[key] = result.data['canonical_text']
    verified = _validate_english(client, normalized)
    if verified.get('valid') is not True or verified.get('violations') != []:
        raise HTTPException(422, detail={'error': 'REQUIREMENT_LANGUAGE_NORMALIZATION_REQUIRED'})
    return normalized


def refresh_provider_graph(db, *, project, requirement, identity, operation_id):
    """Use actual configured dependency APIs; do not reuse stale analysis."""
    from aivan.integrations.giraffe_db import GiraffeDBClient, persist_rfq_gltg_graph
    from aivan.integrations.gltg import GLTGClient
    from aivan.schemas.rfq import RFQStrategy
    from aivan.openclaw.contracts import OpenClawEvent
    from aivan.execution.safety import evaluate_requirement_readiness

    gate = evaluate_requirement_readiness(requirement)
    if not gate.ready:
        raise HTTPException(409, detail={'error': 'REQUIREMENT_CORE_CLARIFICATION_REQUIRED', 'missing_fields': gate.missing_fields})
    strategy = RFQStrategy.model_validate((project.requirement_json or {}).get('strategy') or {})
    event = OpenClawEvent(tenant_id=project.tenant_id, project_id=project.project_id,
        source='myaivan', channel='myaivan', conversation_id=project.conversation_id,
        message_id=operation_id, source_trace_id=operation_id,
        sender_id=project.customer_id, sender_display_name=project.customer_display_name,
        actor_id=identity.actor_id, business_role=identity.business_role.value,
        conversation_role=identity.conversation_role.value, execution_mode='update',
        authorization_basis=identity.authorization_basis, message_text='Human-confirmed requirement clarification')
    provider = GiraffeDBClient(db, tenant_id=project.tenant_id)
    prior_graph = None
    if provider.uses_remote_data_api:
        # Reconcile this operation's existing case before repeating side effects.
        # Its persisted timestamp/GLTG output remain stable after a lost reply.
        from urllib.parse import quote
        from aivan.integrations.giraffe_db import build_graph_trace_metadata, GiraffeDBContextError
        trace = build_graph_trace_metadata(event, project.project_id)
        key = quote(trace['idempotency_key'] + ':procurement-case', safe='')
        try:
            committed = provider._remote_get(f'/api/data/write-results/procurement_cases/{key}')
        except GiraffeDBContextError as exc:
            if str(exc) != 'GIRAFFE_DB_CONTEXT_HTTP_404':
                raise
        else:
            record = committed.get('record') if isinstance(committed, dict) else None
            case_id = record.get('procurement_case_id') if isinstance(record, dict) else None
            if not isinstance(case_id, str) or not case_id:
                raise HTTPException(409, detail={'error': 'REQUIREMENT_PROVIDER_RECOVERY_INVALID'})
            prior_graph = provider._remote_get(f'/api/data/procurement-cases/{quote(case_id, safe="")}/transaction-graph')
            source_case = prior_graph.get('procurement_case') or {}
            if source_case.get('tenant_id') != project.tenant_id or source_case.get('procurement_case_id') != case_id:
                raise HTTPException(409, detail={'error': 'REQUIREMENT_PROVIDER_RECOVERY_CONFLICT'})
            stored = (source_case.get('metadata_json') or {}).get('requirement')
            expected = requirement.model_dump()
            def comparable(value):
                value = copy.deepcopy(value)
                ((value.get('extra') or {}).get('requirement_clarification') or {}).pop('confirmed_at', None)
                return value
            if not isinstance(stored, dict) or comparable(stored) != comparable(expected):
                raise HTTPException(409, detail={'error': 'REQUIREMENT_PROVIDER_RECOVERY_CONFLICT'})
            requirement = BuyerRequirement.model_validate(stored)
    gltg = None
    if isinstance(prior_graph, dict):
        for run in prior_graph.get('gltg_runs', []):
            if (run.get('explanation_json') or {}).get('source_trace_id') == trace['source_trace_id']:
                gltg = run.get('output_json')
                break
    if not isinstance(gltg, dict):
        context = provider.build_context(requirement, customer_id=project.customer_id, user_id=identity.actor_id)
        gltg = GLTGClient().simulate(requirement, strategy, supplier_count=len(context.suppliers),
            tenant_id=project.tenant_id, source_trace_id=operation_id).model_dump()
    graph = persist_rfq_gltg_graph(event=event, project_id=project.project_id,
        requirement=requirement, strategy=strategy, gltg=gltg)
    if provider.uses_remote_data_api:
        if not graph.get('readback_verified'):
            raise HTTPException(503, detail={'error': 'REQUIREMENT_PROVIDER_READBACK_REQUIRED'})
        from urllib.parse import quote
        persisted = provider._remote_get('/api/data/procurement-cases/' + quote(graph['procurement_case_id'], safe='') + '/transaction-graph')
        case = persisted.get('procurement_case') or {}
        rfq = next((row for row in persisted.get('rfqs', []) if row.get('id') == graph['rfq_id']), {})
        if (case.get('tenant_id') != project.tenant_id or rfq.get('tenant_id') != project.tenant_id
                or rfq.get('procurement_case_id') != graph['procurement_case_id']
                or any((row.get('metadata_json') or {}).get('requirement') != requirement.model_dump() for row in (case, rfq))):
            raise HTTPException(409, detail={'error': 'REQUIREMENT_PROVIDER_READBACK_MISMATCH'})
    return graph, strategy.model_dump(), gltg, requirement


def clarify_requirement(db, *, project, fields, expected_hash, context, identity):
    if identity.business_role not in {BusinessRole.BUYER, BusinessRole.SALES, BusinessRole.PROCUREMENT,
                                     BusinessRole.APPROVER, BusinessRole.ADMIN}:
        raise HTTPException(403, detail={'error': 'REQUIREMENT_CLARIFICATION_FORBIDDEN'})
    if not context.idempotency_key:
        raise HTTPException(400, detail={'error': 'REQUIREMENT_IDEMPOTENCY_KEY_REQUIRED'})
    if not fields or set(fields) - EDITABLE_FIELDS:
        raise HTTPException(422, detail={'error': 'REQUIREMENT_FIELD_NOT_EDITABLE'})
    if any(isinstance(value, bool) or not isinstance(value, (str, int, float, type(None)))
           or (isinstance(value, float) and not math.isfinite(value))
           or (isinstance(value, str) and len(value) > 12000) for value in fields.values()):
        raise HTTPException(422, detail={'error': 'REQUIREMENT_VALUE_INVALID'})
    operation_id = 'clarify_' + source_digest(f'{context.tenant_id}\0{project.project_id}\0{identity.actor_id}\0{context.idempotency_key}')
    request_digest = source_digest(json.dumps({'fields': fields, 'expected_hash': expected_hash}, sort_keys=True, ensure_ascii=True, allow_nan=False))
    prior = db.query(AuditLogRecord).filter_by(tenant_id=context.tenant_id, case_id=project.project_id,
        source_trace_id=operation_id, event_type='REQUIREMENT_CLARIFIED').first()
    if prior is not None:
        if prior.after_json.get('request_sha256') != request_digest:
            raise HTTPException(409, detail={'error': 'REQUIREMENT_IDEMPOTENCY_CONFLICT'})
        return {**prior.after_json['result'], 'replayed': True}
    before = dict(project.requirement_json or {})
    if (before.get('order_confirmation') or {}).get('status') == 'confirmed':
        raise HTTPException(409, detail={'error': 'CONFIRMED_ORDER_REQUIRES_AMENDMENT'})
    if requirement_hash(before) != expected_hash:
        raise HTTPException(409, detail={'error': 'REQUIREMENT_VERSION_MISMATCH'})
    canonical = normalize_fields(fields)
    try:
        requirement = BuyerRequirement.model_validate({**snapshot(before), **canonical})
    except ValidationError as exc:
        raise HTTPException(422, detail={'error': 'REQUIREMENT_VALUE_INVALID'}) from exc
    if requirement.quantity is not None and requirement.quantity <= 0:
        raise HTTPException(422, detail={'error': 'REQUIREMENT_QUANTITY_INVALID'})
    requirement.missing_fields = _detect_missing_fields(requirement)
    now = datetime.now(timezone.utc).isoformat()
    sources = dict(requirement.extra.get('field_sources') or {})
    sources.update({key: 'operator_confirmed' for key in canonical})
    requirement.extra = {**requirement.extra, 'field_sources': sources,
        'requirement_clarification': {'source_text_sha256': request_digest, 'actor_id': identity.actor_id,
            'actor_role': identity.business_role.value, 'confirmed_at': now,
            'previous_requirement_sha256': expected_hash, 'confirmed_fields': sorted(canonical)}}
    changed = [key for key in canonical if before.get(key) != canonical[key]]
    material = bool(set(changed) & MATERIAL_FIELDS)
    try:
        graph, strategy, gltg, requirement = refresh_provider_graph(db, project=project, requirement=requirement,
            identity=identity, operation_id=operation_id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(503, detail={'error': 'REQUIREMENT_PROVIDER_REFRESH_FAILED'}) from exc
    now = requirement.extra["requirement_clarification"]["confirmed_at"]
    payload = requirement.model_dump()
    payload.update({'strategy': strategy, 'gltg_simulation': gltg})
    if graph:
        payload['giraffe_db_graph'] = graph
    if material:
        superseded = db.query(InquiryDraftRecord).filter(InquiryDraftRecord.tenant_id == project.tenant_id,
            InquiryDraftRecord.project_id == project.project_id,
            InquiryDraftRecord.status.in_(['pending_approval', 'approved', 'approved_pending_send']))
        for draft in superseded:
            draft.status = 'superseded'
        project.selected_option_json = None
        project.case_state = 'awaiting_supplier'
    else:
        # A non-material note must not erase prior quote/approval state.
        payload = {**before, **payload}
    project.requirement_json = payload
    result = {'case_id': project.project_id, 'requirement': requirement.model_dump(),
        'requirement_sha256': requirement_hash(payload), 'changed_fields': changed,
        'approval_invalidated': material, 'provider_graph': graph, 'replayed': False}
    CaseDomainRepository(db).record_audit(tenant_id=project.tenant_id, case_id=project.project_id,
        event_type='REQUIREMENT_CLARIFIED', identity=identity, source_trace_id=operation_id,
        before={'requirement_sha256': expected_hash}, after={'request_sha256': request_digest, 'result': result})
    ExecutionEventRepository(db).append(project.project_id, 'REQUIREMENT_CLARIFIED',
        'Human clarification recorded; changed commercial requirements require a new quotation review.',
        payload={'previous_requirement_sha256': expected_hash, 'requirement_sha256': result['requirement_sha256'],
            'changed_fields': changed, 'actor_id': identity.actor_id, 'actor_role': identity.business_role.value,
            'confirmed_at': now, 'provider_readback_verified': bool(graph.get('readback_verified'))},
        actor=identity.actor_id, tenant_id=project.tenant_id, source_trace_id=operation_id)
    db.commit()
    return result
