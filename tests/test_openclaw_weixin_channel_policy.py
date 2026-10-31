"""Official Weixin channel IDs retain human-reviewed relay semantics."""
import pytest

from aivan.execution.channel_policy import (
    DeliveryMode, get_channel_capability, is_personal_im_channel, normalize_channel,
    validate_counterparty_draft_channel,
)
from tests.test_stage4_relay import _draft, _tenant_headers, relay_api


def test_official_channel_id_is_a_wechat_alias():
    assert normalize_channel("openclaw-weixin") == "wechat"
    capability = get_channel_capability("openclaw-weixin")
    assert capability.delivery_mode == DeliveryMode.GUIDED_RELAY
    assert capability.requires_human_approval
    assert capability.supports_inbound_relay
    assert is_personal_im_channel("openclaw-weixin")
    with pytest.raises(ValueError, match="blocks direct counterparty delivery"):
        validate_counterparty_draft_channel("openclaw-weixin", "buyer")


@pytest.mark.parametrize("channel", ["wechat", "openclaw-weixin"])
def test_official_channel_approval_is_durable_without_sending(relay_api, monkeypatch, channel):
    client, db = relay_api
    from aivan.db.models import RelayReceiptRecord
    from aivan.db.repositories.draft_repo import DraftRepository
    from aivan.openclaw.client import OpenClawClient

    def forbidden_send(*args, **kwargs):
        pytest.fail("Channel alias must not introduce automatic external sending")

    monkeypatch.setattr(OpenClawClient, "send_message", forbidden_send)
    draft = _draft(db, channel=channel, suffix="official-weixin")
    db.commit()
    path = f"/api/relay/{draft.draft_id}/confirm"
    headers = _tenant_headers(**{"Idempotency-Key": "official-weixin-receipt"})
    receipt = {"receipt_reference": "synthetic-manual-receipt"}
    assert client.post(path, headers=headers, json=receipt).status_code == 409
    assert DraftRepository(db).get(draft.draft_id).status == "pending_approval"
    denied = client.post(f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers("other-tenant"))
    assert denied.status_code == 404
    approved = client.post(f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers())
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved_pending_send"
    assert approved.json()["sent"] is False
    db.expire_all()
    stored = DraftRepository(db).get(draft.draft_id)
    assert stored.approval_id and stored.approved_by
    assert stored.channel == channel
    outbox = client.get("/api/relay/outbox", headers=_tenant_headers()).json()["outbox"]
    assert len(outbox) == 1 and outbox[0]["channel"] == channel
    confirmed = client.post(path, headers=headers, json=receipt)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "relayed"
    replay = client.post(path, headers=headers, json=receipt)
    assert replay.json()["idempotent_replay"] is True
    assert db.query(RelayReceiptRecord).count() == 1


def test_official_channel_still_requires_account_binding(relay_api):
    client, db = relay_api
    draft = _draft(db, channel="openclaw-weixin", suffix="missing-account")
    draft.channel_account_id = ""
    db.commit()
    response = client.post(f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers())
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "RELAY_BINDING_INCOMPLETE"


def test_other_gateway_channels_remain_unsupported():
    assert get_channel_capability("openclaw-unknown").delivery_mode == DeliveryMode.UNSUPPORTED
