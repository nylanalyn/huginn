from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_duration_hours(raw: str) -> int:
    value = raw.strip().lower()
    if value.endswith("h"):
        hours = int(value[:-1])
    elif value.endswith("d"):
        hours = int(value[:-1]) * 24
    else:
        hours = int(value)
    if hours <= 0:
        raise ValueError("duration must be positive")
    return hours


def cutoff_from_hours(now: datetime, hours: int) -> datetime:
    return now - timedelta(hours=hours)
