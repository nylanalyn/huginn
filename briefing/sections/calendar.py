from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import recurring_ical_events
from icalendar import Calendar

from briefing.config import CalendarSectionConfig
from briefing.sections.base import RenderedSection, RunContext

ICS_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class CalendarEvent:
    summary: str
    start: datetime
    end: datetime | None = None
    location: str | None = None
    all_day: bool = False


class CalendarSection:
    name = "calendar"

    def __init__(self, section_config: CalendarSectionConfig) -> None:
        self.section_config = section_config

    def collect(self, context: RunContext) -> list[CalendarEvent]:
        timezone = ZoneInfo(context.config.bot.timezone)
        if self.section_config.source == "json":
            return load_json_calendar(self.section_config, timezone)
        if self.section_config.source == "ics_url":
            return load_ics_url_calendar(self.section_config, timezone)
        if self.section_config.source == "caldav":
            raise NotImplementedError("calendar source 'caldav' is configured but not implemented yet")
        raise ValueError(f"Unsupported calendar source: {self.section_config.source}")

    def select(self, items: list[CalendarEvent], context: RunContext) -> list[CalendarEvent]:
        timezone = ZoneInfo(context.config.bot.timezone)
        now = datetime.now(timezone)
        window_end = now + timedelta(hours=self.section_config.lookahead_hours)
        selected = [
            item
            for item in items
            if event_in_window(item, now=now, window_end=window_end)
        ]
        selected.sort(key=lambda item: (item.start, item.summary.lower()))
        return selected

    def render(self, items: list[CalendarEvent], context: RunContext) -> RenderedSection:
        timezone = ZoneInfo(context.config.bot.timezone)
        if not items:
            return RenderedSection(title="Calendar", lines=["No events in the next window."])
        return RenderedSection(
            title="Calendar",
            lines=[format_event(item, timezone) for item in items],
        )


def load_json_calendar(config: CalendarSectionConfig, timezone: ZoneInfo) -> list[CalendarEvent]:
    if not config.json_path:
        raise ValueError("calendar source 'json' requires json_path")
    path = Path(config.json_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_events = data.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("calendar JSON must contain an events list")
    return [parse_event(raw_event, timezone) for raw_event in raw_events]


def load_ics_url_calendar(config: CalendarSectionConfig, timezone: ZoneInfo) -> list[CalendarEvent]:
    if not config.ics_url_env:
        raise ValueError("calendar source 'ics_url' requires ics_url_env")
    url = os.getenv(config.ics_url_env)
    if not url:
        raise ValueError(f"calendar URL environment variable {config.ics_url_env} is not set")

    response = httpx.get(url, timeout=ICS_TIMEOUT_SECONDS, follow_redirects=True)
    response.raise_for_status()
    window_start = datetime.now(timezone)
    window_end = window_start + timedelta(hours=config.lookahead_hours)
    return parse_ics_calendar(
        response.content,
        timezone,
        window_start=window_start,
        window_end=window_end,
    )


def parse_ics_calendar(
    content: bytes,
    timezone: ZoneInfo,
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[CalendarEvent]:
    # Expand recurrence rules (RRULE/RDATE/EXDATE and overrides) into concrete
    # occurrences within the lookahead window. A plain VEVENT walk would only
    # ever see the first instance of a repeating event, so weekly meetings would
    # silently never appear.
    calendar = Calendar.from_ical(content)
    occurrences = recurring_ical_events.of(calendar).between(window_start, window_end)
    events: list[CalendarEvent] = []
    for component in occurrences:
        summary = str(component.get("summary", "")).strip()
        dtstart = component.get("dtstart")
        if not summary or dtstart is None:
            continue

        start_value = dtstart.dt
        dtend = component.get("dtend")
        end_value = dtend.dt if dtend is not None else None
        location = component.get("location")
        all_day = isinstance(start_value, date) and not isinstance(start_value, datetime)

        events.append(
            CalendarEvent(
                summary=summary,
                start=_ics_value_to_datetime(start_value, timezone),
                end=_ics_value_to_datetime(end_value, timezone) if end_value is not None else None,
                location=str(location).strip() if location else None,
                all_day=all_day,
            )
        )
    events.sort(key=lambda event: event.start)
    return events


def parse_event(raw_event: dict[str, Any], timezone: ZoneInfo) -> CalendarEvent:
    summary = str(raw_event.get("summary", "")).strip()
    start_raw = raw_event.get("start")
    if not summary:
        raise ValueError("calendar event missing summary")
    if not start_raw:
        raise ValueError(f"calendar event '{summary}' missing start")

    all_day = bool(raw_event.get("all_day", False))
    start = parse_calendar_datetime(str(start_raw), timezone, all_day=all_day)
    end_raw = raw_event.get("end")
    end = parse_calendar_datetime(str(end_raw), timezone, all_day=all_day) if end_raw else None
    location = raw_event.get("location")
    return CalendarEvent(
        summary=summary,
        start=start,
        end=end,
        location=str(location).strip() if location else None,
        all_day=all_day,
    )


def parse_calendar_datetime(raw_value: str, timezone: ZoneInfo, *, all_day: bool) -> datetime:
    value = raw_value.strip()
    if _is_date_only(value):
        parsed_date = date.fromisoformat(value)
        return datetime.combine(parsed_date, time.min, tzinfo=timezone)

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _ics_value_to_datetime(value: date | datetime, timezone: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone)
        return value.astimezone(timezone)
    return datetime.combine(value, time.min, tzinfo=timezone)


def event_in_window(event: CalendarEvent, *, now: datetime, window_end: datetime) -> bool:
    if event.all_day:
        local_today = now.date()
        local_window_end = window_end.date()
        return local_today <= event.start.date() <= local_window_end

    event_end = event.end or event.start
    return event.start < window_end and event_end >= now


def format_event(event: CalendarEvent, timezone: ZoneInfo) -> str:
    start = event.start.astimezone(timezone)
    if event.all_day:
        prefix = "All day"
    else:
        prefix = _format_time(start)
        if event.end:
            end = event.end.astimezone(timezone)
            prefix += f"-{_format_time(end)}"

    line = f"{prefix} - {event.summary}"
    if event.location:
        line += f" ({event.location})"
    return line


def _format_time(value: datetime) -> str:
    hour = value.hour
    minute = value.minute
    suffix = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12
    return f"{hour_12}:{minute:02d} {suffix}"


def _is_date_only(value: str) -> bool:
    return len(value) == 10 and value[4] == "-" and value[7] == "-"
