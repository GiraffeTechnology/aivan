"""In-process store for pending questionnaires and assembled signals.

Tech debt (per iteration spec): the canonical home for SupplierStateSignal is a
``supplier_state_signals`` table in giraffe-db, indexed on (supplier_id,
enquiry_id). Until that migration lands this keeps the state in aivan's process
memory behind a narrow interface, so swapping in a giraffe-db-backed store later
touches only this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aivan.supplier_signals.models import SupplierStateSignal

_Key = tuple[str, str]  # (supplier_id, enquiry_id)


@dataclass
class PendingQuestionnaire:
    """State recorded when a questionnaire is dispatched, used for speed scoring."""

    supplier_id: str
    enquiry_id: str
    sent_at: datetime           # UTC
    supplier_timezone: str
    historical_avg_response_hours: float


class SignalStore:
    """Narrow keyed store: pending questionnaires + assembled signals."""

    def __init__(self) -> None:
        self._pending: dict[_Key, PendingQuestionnaire] = {}
        self._signals: dict[_Key, SupplierStateSignal] = {}

    # --- pending questionnaires --- #
    def put_pending(self, pending: PendingQuestionnaire) -> None:
        self._pending[(pending.supplier_id, pending.enquiry_id)] = pending

    def get_pending(self, supplier_id: str, enquiry_id: str) -> PendingQuestionnaire | None:
        return self._pending.get((supplier_id, enquiry_id))

    # --- assembled signals --- #
    def put_signal(self, signal: SupplierStateSignal) -> None:
        self._signals[(signal.supplier_id, signal.enquiry_id)] = signal

    def get_signal(self, supplier_id: str, enquiry_id: str) -> SupplierStateSignal | None:
        return self._signals.get((supplier_id, enquiry_id))

    def signals_for_enquiry(self, enquiry_id: str) -> dict[str, SupplierStateSignal]:
        """All assembled signals for an enquiry, keyed by supplier_id."""
        return {
            sid: sig
            for (sid, eid), sig in self._signals.items()
            if eid == enquiry_id
        }
