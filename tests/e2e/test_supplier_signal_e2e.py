"""End-to-end supplier-signal flow (Task 3).

enquiry dispatched -> questionnaire sent -> fast reply + slow no-reply ->
behaviour observed -> LLM extraction -> signal assembled -> GLTG enumerate with
supplier_state_overrides -> decision packet carries risk flags.

GLTG HTTP calls are routed to the in-memory fake (autouse fixture in conftest),
which honours supplier_state_overrides exactly as the real GLTG service does.
"""

from __future__ import annotations

from datetime import date, datetime

from aivan.supplier_signals.assembler import assemble_signal
from aivan.supplier_signals.behaviour_observer import no_response_behaviour, observe_response
from aivan.supplier_signals.gltg_wiring import enumerate_with_signals
from aivan.supplier_signals.llm_extractor import extract_supplier_state
from aivan.supplier_signals.models import EnquiryContext, ExtractionResult, LoadLevel, RiskFlag
from aivan.supplier_signals.questionnaire import QuestionnaireDispatcher, questionnaire_text
from aivan.supplier_signals.store import SignalStore

TZ = "UTC"
ENQUIRY_ID = "ENQ-E2E"
ENQUIRY_DATE = date(2026, 6, 27)
SENT_AT = datetime(2026, 6, 29, 9)  # Monday 09:00


class FakeProvider:
    def __init__(self, name, result):
        self.provider_name = name
        self._result = result

    def complete_json(self, *a, **k):
        return self._result


def _supplier(sid):
    return {
        "supplier_id": sid,
        "capacity_per_day": 5000,
        "material_ready_days": 5,
        "production_days": 20,
        "qc_days": 3,
        "logistics_days": 30,
        "confidence": 0.8,
    }


def test_full_signal_flow():
    store = SignalStore()
    sent_messages: list[tuple[str, str]] = []
    dispatcher = QuestionnaireDispatcher(
        send_fn=lambda sid, msg: sent_messages.append((sid, msg)),
        store=store,
        clock=lambda: SENT_AT,
    )

    # 1. Dispatch enquiry -> questionnaire to both suppliers.
    for sid in ("FastFab", "SlowFab"):
        dispatcher.dispatch(sid, ENQUIRY_ID, supplier_timezone=TZ, historical_avg_response_hours=10.0)
    assert len(sent_messages) == 2
    assert all(msg == questionnaire_text("zh") for _, msg in sent_messages)

    context = EnquiryContext(quantity=10000, product_type="men_shirt", enquiry_date=ENQUIRY_DATE)

    # 2a. Fast supplier replies quickly and completely.
    fast_pending = store.get_pending("FastFab", ENQUIRY_ID)
    fast_behaviour = observe_response(
        fast_pending.sent_at,
        datetime(2026, 6, 29, 11),  # 2 working hours -> fast
        "日产量大概3000件，下周就能开始，目前产能比较空闲",
        fast_pending.supplier_timezone,
        fast_pending.historical_avg_response_hours,
    )
    fast_extraction = extract_supplier_state(
        "日产量大概3000件，下周就能开始，目前产能比较空闲",
        context,
        primary=FakeProvider("ollama", {"load_level": "LIGHT", "extraction_confidence": 0.9}),
        fallback=FakeProvider("qwen", {}),
    )
    fast_signal = assemble_signal(
        "FastFab", ENQUIRY_ID, fast_behaviour, fast_extraction, ENQUIRY_DATE,
        raw_reply="日产量大概3000件，下周就能开始，目前产能比较空闲",
    )
    store.put_signal(fast_signal)

    # 2b. Slow supplier never replies within 24 working hours.
    slow_signal = assemble_signal(
        "SlowFab", ENQUIRY_ID, no_response_behaviour(), ExtractionResult.empty(), ENQUIRY_DATE,
    )
    store.put_signal(slow_signal)

    # 3. Signals assembled correctly for both.
    assert fast_signal.load_level == LoadLevel.LIGHT
    assert fast_signal.risk_flags == []
    assert RiskFlag.NO_RESPONSE in slow_signal.risk_flags

    # 4-6. GLTG enumerate with overrides -> decision packet.
    order = {"product_type": "apparel", "quantity": 10000}
    suppliers = [_supplier("FastFab"), _supplier("SlowFab")]
    signals = store.signals_for_enquiry(ENQUIRY_ID)
    packet = enumerate_with_signals(order, suppliers, signals)

    by_supplier = {o.supplier_id: o for o in packet.options}
    # Fast supplier ranked above the slow/no-reply supplier.
    assert by_supplier["FastFab"].rank < by_supplier["SlowFab"].rank
    # NO_RESPONSE flag surfaces as a visible warning on the non-responding option.
    assert RiskFlag.NO_RESPONSE.value in by_supplier["SlowFab"].risk_flags
    assert any("NO_RESPONSE" in w for w in by_supplier["SlowFab"].warnings)
    # Fast supplier carries no warnings.
    assert by_supplier["FastFab"].warnings == []
