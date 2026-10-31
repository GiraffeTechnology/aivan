"""Durable, non-retryable claim before an external delivery attempt."""


def claim_delivery(db, draft, expected_status: str) -> bool:
    """Commit approved identity before I/O; a crash must never enable resend."""
    changed = db.query(type(draft)).filter(
        type(draft).draft_id == draft.draft_id,
        type(draft).tenant_id == draft.tenant_id,
        type(draft).status == expected_status,
        type(draft).approval_id == draft.approval_id,
        type(draft).message_text == draft.message_text,
        type(draft).target_peer_id == draft.target_peer_id,
        type(draft).channel_account_id == draft.channel_account_id,
    ).update({"status": "delivery_unconfirmed"}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        return False
    db.commit()
    db.refresh(draft)
    return True
