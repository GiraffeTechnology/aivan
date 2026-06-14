from datetime import datetime, timezone, timedelta
import re

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def days_from_now(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def days_between(start_iso: str, end_iso: str) -> int:
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    return max(0, (end - start).days)

def days_until(end_iso: str) -> int:
    return days_between(utcnow_iso(), end_iso)

def deadline_days(deadline_iso: str) -> int:
    return days_until(deadline_iso)
