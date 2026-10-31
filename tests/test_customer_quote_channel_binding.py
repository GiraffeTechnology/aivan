"""Quote review retains the authenticated buyer thread, not supplier routing."""
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution.rfq_execution import _create_customer_quote_email_draft
from aivan.openclaw.contracts import OpenClawEvent


def test_customer_quote_preserves_original_buyer_channel_account(db_session):
    project = ProjectRepository(db_session).create(
        conversation_id="buyer-thread", customer_id="buyer-peer", channel="whatsapp",
        channel_account_id="buyer-account", tenant_id="tenant-a",
    )
    event = OpenClawEvent(
        conversation_id="supplier-thread", channel="email",
        channel_account_id="supplier-account", tenant_id="tenant-a",
    )
    ids = _create_customer_quote_email_draft(project, event, [], db_session)
    draft = DraftRepository(db_session).get(ids[0], tenant_id="tenant-a")
    assert draft.channel == "whatsapp"
    assert draft.channel_account_id == "buyer-account"
    assert draft.conversation_id == "buyer-thread"
    assert draft.target_peer_id == "buyer-peer"
    assert draft.status == "pending_approval"
