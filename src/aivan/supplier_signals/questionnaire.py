"""Questionnaire dispatch on enquiry events.

Sends the three-question state questionnaire to the supplier via the existing
communication channel (injected ``send_fn``) and records pending state keyed by
(supplier_id, enquiry_id) so the behaviour observer can later score response speed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from aivan.supplier_signals.store import PendingQuestionnaire, SignalStore

# Questionnaire text (Simplified Chinese -- the supplier's preferred language).
# Three active signals: daily capacity, earliest start, current load.
QUESTIONNAIRE_TEXT_ZH = (
    "您好，感谢您对本次询盘的关注。请问：\n"
    "1. 目前每天可接新单的生产量大概是多少？\n"
    "2. 最早什么时候可以开始生产本次订单？\n"
    "3. 目前产能占用情况如何？\n\n"
    "您可以直接用文字回复，无需填写表格。"
)

QUESTIONNAIRE_TEXT_EN = (
    "Hello, thank you for your interest in this enquiry. Could you let us know:\n"
    "1. Roughly how many units per day can you currently take on for new orders?\n"
    "2. What is the earliest you could start production for this order?\n"
    "3. How heavily is your capacity currently committed?\n\n"
    "You can reply in plain text -- no form required."
)

# send_fn(supplier_id, message_text) -> None. Transport (email/WeChat/...) is
# owned by the caller; the dispatcher stays channel-agnostic.
SendFn = Callable[[str, str], None]


def questionnaire_text(language: str = "zh") -> str:
    return QUESTIONNAIRE_TEXT_EN if (language or "zh").lower().startswith("en") else QUESTIONNAIRE_TEXT_ZH


class QuestionnaireDispatcher:
    """Sends the state questionnaire and records pending state for scoring."""

    def __init__(
        self,
        send_fn: SendFn,
        store: SignalStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._send = send_fn
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def dispatch(
        self,
        supplier_id: str,
        enquiry_id: str,
        supplier_timezone: str,
        historical_avg_response_hours: float,
        language: str = "zh",
    ) -> PendingQuestionnaire:
        """Send the questionnaire and persist pending state. Returns the record."""
        sent_at = self._clock()
        self._send(supplier_id, questionnaire_text(language))
        pending = PendingQuestionnaire(
            supplier_id=supplier_id,
            enquiry_id=enquiry_id,
            sent_at=sent_at,
            supplier_timezone=supplier_timezone,
            historical_avg_response_hours=historical_avg_response_hours,
        )
        self._store.put_pending(pending)
        return pending
