from aivan.db.models.intake import InquiryMessage, InquirySheet
from aivan.intake.persistence import persist_inquiry_intake
from aivan.openclaw.contracts import OpenClawEvent


def _event(text: str, *, conversation_id: str = "conv-1", sender_id: str = "wx-user") -> OpenClawEvent:
    return OpenClawEvent(
        source="openclaw",
        channel="openclaw-weixin",
        conversation_id=conversation_id,
        sender_id=sender_id,
        message_text=text,
    )


def test_same_inquiry_appends_to_existing_sheet(db_session):
    first = persist_inquiry_intake(_event("询价5000件格子衬衫，45天交东京，高品质"), db_session)
    second = persist_inquiry_intake(_event("格子衬衫5000件，45天东京，高品质"), db_session)

    assert second.sheet_id == first.sheet_id
    assert second.match_decision == "same_existing"
    assert db_session.query(InquirySheet).count() == 1
    assert db_session.query(InquiryMessage).count() == 2


def test_different_inquiry_creates_new_sheet(db_session):
    first = persist_inquiry_intake(_event("询价5000件格子衬衫，45天交东京，高品质"), db_session)
    second = persist_inquiry_intake(_event("询价1000件纯棉T恤，交加拿大"), db_session)

    assert second.sheet_id != first.sheet_id
    assert second.match_decision in {"new_temporary", "new_confirmed"}
    assert db_session.query(InquirySheet).count() == 2
    assert db_session.query(InquiryMessage).count() == 2


def test_uncertain_inquiry_creates_temporary_unconfirmed_sheet(db_session):
    message = persist_inquiry_intake(_event("这个也帮我问一下"), db_session)
    sheet = db_session.query(InquirySheet).filter(InquirySheet.id == message.sheet_id).one()

    assert message.match_decision == "uncertain_new"
    assert sheet.status == "temporary_unconfirmed"
    assert db_session.query(InquiryMessage).count() == 1
