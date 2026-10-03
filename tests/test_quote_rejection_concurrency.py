"""Local file-backed transaction tests, with fixture-only model outputs."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from aivan.db.models import Base
from aivan.db.models.domain import ApprovalRecord, AuditLogRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.models.project import Project
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.domain.roles import normalize_actor_identity
from aivan.execution.draft_rejection import reject_draft_atomically
from aivan.execution.approval_state import DraftStateError

@pytest.fixture
def records(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'race.db'), connect_args={'timeout': 10})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        p = ProjectRepository(db).create('test-thread', 'buyer', tenant_id='race')
        p.case_state = 'awaiting_approval'
        p.requirement_json = {'project_id': p.project_id, 'quantity': 10}
        d = DraftRepository(db).create(p.project_id, dict(tenant_id='race', target_role='customer',
            channel='email', status='pending_approval', message_text='test',
            notes='draft_type=customer_quote_email', target_peer_id='buyer'))
        db.commit()
        ids = p.project_id, d.draft_id
    yield sessions, ids
    engine.dispose()

def reject(db, draft):
    return reject_draft_atomically(db=db, draft=draft, source_trace_id='race-reject',
        identity=normalize_actor_identity(actor_id='approver', business_role='approver',
                                         authorization_basis='test-principal'))

def test_locked_project_refreshes_retained_identity(records):
    sessions, (pid, _) = records
    with sessions() as a, sessions() as b:
        retained = a.get(Project, pid)
        b.get(Project, pid).case_state = 'supplier_replied'
        b.commit()
        locked = ProjectRepository(a).get_for_update(pid, tenant_id='race')
        assert locked is retained
        assert locked.case_state == 'supplier_replied'

def test_rejection_revalidates_draft_after_lock(records):
    sessions, (_, did) = records
    with sessions() as a, sessions() as b:
        retained = a.get(InquiryDraftRecord, did)
        b.get(InquiryDraftRecord, did).status = 'superseded'
        b.commit()
        with pytest.raises(DraftStateError):
            reject(a, retained)
        a.rollback()
    with sessions() as db:
        assert db.get(InquiryDraftRecord, did).status == 'superseded'
        assert db.query(ApprovalRecord).count() == db.query(AuditLogRecord).count() == 0

@pytest.mark.parametrize('first_lane', ['reject', 'regenerate'])
def test_transaction_orderings(records, monkeypatch, first_lane):
    from aivan.execution import rfq_execution as w
    from aivan.openclaw.contracts import OpenClawEvent
    from aivan.schemas.rfq import EventClassification
    from aivan.schemas.response import SupplierReply
    from aivan.schemas.leadtime import LeadTimeEstimate
    from aivan.schemas.quote import BuyerOption
    from aivan.schemas.rfq import FallbackTrigger, GLTGSimulation
    from aivan.openclaw import outbound_approval
    sessions, (pid, did) = records
    sends = []
    monkeypatch.setattr(outbound_approval, 'send_if_approved', lambda *a, **k: sends.append(True))
    monkeypatch.setattr(w, 'bind_conversation', lambda *a: None)
    monkeypatch.setattr(w, 'parse_supplier_reply', lambda **k: SupplierReply(
        project_id=pid, supplier_id='supplier', raw_text='fixture', unit_price=1))
    lead = LeadTimeEstimate(estimate_id='fixture', project_id=pid, category='test',
        calculated_lead_time_days=2, earliest_possible_days=1, expected_days=2,
        conservative_days=3, p50_days=1, p80_days=2, p90_days=3, risk_buffer_days=0)
    monkeypatch.setattr(w, 'calculate_leadtime_for_requirement', lambda *a, **k: lead)
    monkeypatch.setattr(w, 'generate_buyer_options', lambda *a: [BuyerOption(
        option_id='fixture', project_id=pid, option_label='test', option_type='test')])
    gltg = GLTGSimulation(
        p50_days=1,
        p80_days=2,
        p90_days=3,
        minimum_feasible_days=1,
        supplier_set_feasibility='sufficient',
        known_suppliers_first_feasibility='feasible',
        public_bidding_time_cost_days=0,
        fallback_trigger_recommendation=FallbackTrigger(),
        selected_confidence_days=2,
    )
    monkeypatch.setattr(w.GLTGClient, 'simulate', lambda *a, **k: gltg)
    locked, attempted, done = Event(), Event(), Event()
    original = ProjectRepository.get_for_update
    def lock(repo, *a, **k):
        if repo.db.info['lane'] != first_lane:
            attempted.set()
            result = original(repo, *a, **k)
            assert done.wait(5)
            return result
        result = original(repo, *a, **k)
        locked.set()
        assert attempted.wait(5)
        return result
    monkeypatch.setattr(ProjectRepository, 'get_for_update', lock)
    def run(lane):
        with sessions() as db:
            db.info['lane'] = lane
            retained = db.get(Project, pid)
            draft = db.get(InquiryDraftRecord, did)
            if lane != first_lane:
                assert locked.wait(5)
            try:
                if lane == 'reject':
                    reject(db, draft)
                    db.commit()
                else:
                    event = OpenClawEvent(channel='email', conversation_id='supplier-thread',
                        sender_id='supplier', actor_id='supplier', business_role='supplier',
                        role_context='supplier', tenant_id='race', project_id=pid,
                        message_text='fixture', source_trace_id='race-reply')
                    w._handle_supplier_reply_event(event, EventClassification(
                        event_type='supplier_reply', project_id=pid, confidence=1,
                        reason='fixture', validated_project_attachment=True), db)
                assert retained is not None
                return 'committed'
            except DraftStateError:
                db.rollback()
                return 'conflict'
            finally:
                if lane == first_lane:
                    done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(run, first_lane)
        b = pool.submit(run, 'regenerate' if first_lane == 'reject' else 'reject')
        assert a.result(timeout=15) == 'committed'
        assert b.result(timeout=15) == ('committed' if first_lane == 'reject' else 'conflict')
    with sessions() as db:
        assert db.get(Project, pid).case_state == 'awaiting_approval'
        assert len(db.get(Project, pid).requirement_json['supplier_replies']) == 1
        drafts = db.query(InquiryDraftRecord).filter_by(project_id=pid).all()
        assert sum(d.status == 'pending_approval' for d in drafts) == 1
        assert db.get(InquiryDraftRecord, did).status == (
            'rejected' if first_lane == 'reject' else 'superseded')
        assert db.query(ApprovalRecord).count() == (1 if first_lane == 'reject' else 0)
        audits = db.query(AuditLogRecord).all()
        assert all(a.tenant_id == 'race' for a in audits)
        assert sum(a.event_type == 'DRAFT_REJECTED' for a in audits) == (1 if first_lane == 'reject' else 0)
        transitions = [a for a in audits if a.event_type == 'CASE_STATE_TRANSITION']
        assert len(transitions) == (2 if first_lane == 'reject' else 0)
        if transitions:
            assert transitions[-1].after_json == {'case_state': 'awaiting_approval'}
    assert sends == []
