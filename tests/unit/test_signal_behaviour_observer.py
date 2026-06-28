"""Tests for the deterministic response-behaviour observer (Task 1)."""

from __future__ import annotations

from datetime import datetime

from aivan.supplier_signals.behaviour_observer import (
    observe_response,
    working_hours_between,
)

TZ = "UTC"  # window Mon-Sat 08:00-20:00; 2026-06-29 is a Monday.
_FULL_REPLY = "日产量大概1500件，下个月初可以开始生产，目前比较忙"


def _dt(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm)


def test_speed_score_1_when_within_historical_average():
    sent = _dt(2026, 6, 29, 9)
    reply = _dt(2026, 6, 29, 11)  # 2 working hours later
    b = observe_response(sent, reply, _FULL_REPLY, TZ, historical_avg_response_hours=10.0)
    assert b.response_speed_score == 1.0


def test_speed_score_half_when_twice_historical_average():
    sent = _dt(2026, 6, 29, 9)
    reply = _dt(2026, 6, 29, 13)  # 4 working hours vs historical 2 -> 0.5
    b = observe_response(sent, reply, _FULL_REPLY, TZ, historical_avg_response_hours=2.0)
    assert b.actual_working_hours == 4.0
    assert b.response_speed_score == 0.5


def test_speed_score_zero_when_over_24_working_hours():
    sent = _dt(2026, 6, 29, 9)
    reply = _dt(2026, 7, 3, 18)  # several working days later (>24 working hours)
    b = observe_response(sent, reply, _FULL_REPLY, TZ, historical_avg_response_hours=10.0)
    assert b.actual_working_hours > 24.0
    assert b.response_speed_score == 0.0
    assert b.responded is True  # still a reply -> NO_RESPONSE not raised here


def test_non_working_hours_are_excluded():
    sent = _dt(2026, 6, 29, 19)   # Mon 19:00 -> 1 working hour to 20:00
    reply = _dt(2026, 6, 30, 9)   # Tue 09:00 -> 1 working hour from 08:00; night excluded
    hours = working_hours_between(sent, reply, TZ)
    assert hours == 2.0


def test_sunday_is_excluded():
    # 2026-07-05 is a Sunday; spanning it must not add working hours for that day.
    sent = _dt(2026, 7, 4, 19)    # Sat 19:00 -> 1h
    reply = _dt(2026, 7, 6, 9)    # Mon 09:00 -> 1h; Sunday contributes 0
    assert working_hours_between(sent, reply, TZ) == 2.0


def test_completeness_score_counts_topics():
    sent = _dt(2026, 6, 29, 9)
    reply = _dt(2026, 6, 29, 10)
    cases = {
        "你好": 0,
        "日产量大概1500件": 1,
        "日产量1500件，目前比较忙": 2,
        _FULL_REPLY: 3,
    }
    for text, expected in cases.items():
        b = observe_response(sent, reply, text, TZ, historical_avg_response_hours=10.0)
        assert b.found_topics == expected, text
        assert b.completeness_score == round(expected / 3.0, 4)
