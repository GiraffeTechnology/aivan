"""Deterministic response-behaviour observation.

Computes response_speed_score and completeness_score from a supplier reply.
Makes NO LLM call -- pure, testable computation (Task 1 DoD).
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from aivan.supplier_signals.models import ResponseBehaviour

# Standard supplier working window: Mon-Sat, 08:00-20:00 local time.
_WORK_START = time(8, 0)
_WORK_END = time(20, 0)
_WORKING_DAYS = frozenset({0, 1, 2, 3, 4, 5})  # Mon..Sat (Python weekday: Mon=0)

# A reply taking more than this many working hours scores 0.0 (still a reply).
_MAX_WORKING_HOURS = 24.0

# Topic detectors for the three questionnaire fields. Substring/regex cues span
# Chinese and English so a free-text reply in either language is scored.
_CAPACITY_CUES = re.compile(
    r"(产量|产能|日产|每天.*?(生产|产)|capacity|per\s*day|pcs|件/|件\s*左右|units?)",
    re.IGNORECASE,
)
_DATE_CUES = re.compile(
    r"(开始|最早|交期|月|下个月|本月|周|星期|号|日\b|date|start|week|month|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_LOAD_CUES = re.compile(
    r"(占用|忙|满产|空闲|产能.*情况|负荷|排产|档期|busy|full|load|idle|free|tight)",
    re.IGNORECASE,
)


def _to_local(dt: datetime, tz: ZoneInfo) -> datetime:
    """Interpret naive datetimes as UTC, then convert to the supplier's tz."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz)


def working_hours_between(start: datetime, end: datetime, timezone: str) -> float:
    """Elapsed working hours between two instants, excluding non-working time.

    Working time is Mon-Sat 08:00-20:00 in the supplier's timezone; hours outside
    that window (nights, Sundays) are not counted so an overnight delay is not
    penalised. Returns 0.0 if end precedes start.
    """
    tz = ZoneInfo(timezone)
    start_local = _to_local(start, tz)
    end_local = _to_local(end, tz)
    if end_local <= start_local:
        return 0.0

    total = timedelta()
    day = start_local.date()
    last_day = end_local.date()
    while day <= last_day:
        if day.weekday() in _WORKING_DAYS:
            window_open = datetime.combine(day, _WORK_START, tzinfo=tz)
            window_close = datetime.combine(day, _WORK_END, tzinfo=tz)
            lo = max(window_open, start_local)
            hi = min(window_close, end_local)
            if hi > lo:
                total += hi - lo
        day += timedelta(days=1)
    return total.total_seconds() / 3600.0


def _count_topics(reply_text: str) -> int:
    """How many of the three questionnaire topics appear in the reply (0-3)."""
    text = reply_text or ""
    found = 0
    if _CAPACITY_CUES.search(text):
        found += 1
    if _DATE_CUES.search(text):
        found += 1
    if _LOAD_CUES.search(text):
        found += 1
    return found


def observe_response(
    sent_at: datetime,
    reply_received_at: datetime,
    reply_text: str,
    supplier_timezone: str,
    historical_avg_response_hours: float,
) -> ResponseBehaviour:
    """Compute response_speed_score and completeness_score for a reply.

    speed = min(1.0, historical_avg / actual_working_hours); a reply taking more
    than 24 working hours scores 0.0 (it is still a reply -- NO_RESPONSE is only
    for the no-reply case, handled by the assembler).
    completeness = found_topics / 3.
    """
    actual = working_hours_between(sent_at, reply_received_at, supplier_timezone)
    found = _count_topics(reply_text)
    completeness = found / 3.0

    if actual > _MAX_WORKING_HOURS:
        speed = 0.0
    elif actual <= 0 or historical_avg_response_hours <= 0:
        # Replied within the same working instant (or no historical baseline):
        # treat as at-or-faster-than-average.
        speed = 1.0
    else:
        speed = min(1.0, historical_avg_response_hours / actual)

    return ResponseBehaviour(
        response_speed_score=round(speed, 4),
        completeness_score=round(completeness, 4),
        responded=True,
        actual_working_hours=round(actual, 4),
        found_topics=found,
    )


def no_response_behaviour() -> ResponseBehaviour:
    """Behaviour for a supplier that did not reply within 24 working hours."""
    return ResponseBehaviour(
        response_speed_score=0.0,
        completeness_score=0.0,
        responded=False,
        actual_working_hours=None,
        found_topics=0,
    )
