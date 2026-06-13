from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from briefing.config import load_config
from briefing.core import render_sections
from briefing.sections.base import RunContext
from briefing.sections.calendar import (
    CalendarEvent,
    CalendarSection,
    event_in_window,
    format_event,
    load_json_calendar,
    parse_ics_calendar,
)


def test_calendar_json_backend_parses_timed_all_day_and_location(tmp_path: Path) -> None:
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(
        """
        {
          "events": [
            {
              "summary": "Standup",
              "start": "2026-06-11T09:00:00-04:00",
              "end": "2026-06-11T09:30:00-04:00",
              "location": "Zoom"
            },
            {
              "summary": "Trash day",
              "start": "2026-06-12",
              "all_day": true
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [bot]
        timezone = "America/New_York"

        [sections.calendar]
        type = "calendar"
        source = "json"
        json_path = "{calendar_path}"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    events = load_json_calendar(config.sections["calendar"], ZoneInfo("America/New_York"))

    assert [event.summary for event in events] == ["Standup", "Trash day"]
    assert events[0].location == "Zoom"
    assert events[1].all_day is True
    assert format_event(events[0], ZoneInfo("America/New_York")) == "9:00 AM-9:30 AM - Standup (Zoom)"
    assert format_event(events[1], ZoneInfo("America/New_York")) == "All day - Trash day"


def test_calendar_window_includes_current_all_day_event() -> None:
    timezone = ZoneInfo("America/New_York")
    now = datetime(2026, 6, 12, 9, 0, tzinfo=timezone)
    event = CalendarEvent(
        summary="Trash day",
        start=datetime(2026, 6, 12, 0, 0, tzinfo=timezone),
        all_day=True,
    )

    assert event_in_window(event, now=now, window_end=now + timedelta(hours=24))


def test_calendar_section_sorts_and_filters_events(tmp_path: Path) -> None:
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(
        """
        {
          "events": [
            {"summary": "Tomorrow", "start": "2026-06-13T08:00:00-04:00"},
            {"summary": "Soon", "start": "2026-06-12T10:00:00-04:00"},
            {"summary": "Past", "start": "2026-06-12T07:00:00-04:00"}
          ]
        }
        """,
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [bot]
        timezone = "America/New_York"

        [sections.calendar]
        type = "calendar"
        source = "json"
        json_path = "{calendar_path}"
        lookahead_hours = 12
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    section = CalendarSection(config.sections["calendar"])
    items = [
        CalendarEvent("Tomorrow", datetime.now(ZoneInfo("America/New_York")) + timedelta(hours=24)),
        CalendarEvent("Soon", datetime.now(ZoneInfo("America/New_York")) + timedelta(hours=1)),
        CalendarEvent("Later", datetime.now(ZoneInfo("America/New_York")) + timedelta(hours=2)),
    ]

    selected = section.select(items, RunContext(config=config))

    assert [item.summary for item in selected] == ["Soon", "Later"]


def test_missing_calendar_file_becomes_section_notice(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [bot]
        timezone = "America/New_York"

        [sections.calendar]
        type = "calendar"
        source = "json"
        json_path = "{tmp_path / "missing.json"}"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    rendered = render_sections(["calendar"], RunContext(config=config))

    assert rendered[0].title == "Calendar"
    assert "Section failed" in rendered[0].lines[0]


def test_unimplemented_caldav_source_becomes_section_notice(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [bot]
        timezone = "America/New_York"

        [sections.calendar]
        type = "calendar"
        source = "caldav"
        caldav_url_env = "CALDAV_URL"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    rendered = render_sections(["calendar"], RunContext(config=config))

    assert rendered[0].title == "Calendar"
    assert "not implemented yet" in rendered[0].lines[0]


def test_ics_calendar_parses_timed_and_all_day_events() -> None:
    ics = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:timed@example.com
DTSTART:20260612T130000Z
DTEND:20260612T133000Z
SUMMARY:Standup
LOCATION:Zoom
END:VEVENT
BEGIN:VEVENT
UID:allday@example.com
DTSTART;VALUE=DATE:20260613
SUMMARY:Trash day
END:VEVENT
END:VCALENDAR
"""

    events = parse_ics_calendar(ics, ZoneInfo("America/New_York"))

    assert [event.summary for event in events] == ["Standup", "Trash day"]
    assert events[0].location == "Zoom"
    assert format_event(events[0], ZoneInfo("America/New_York")) == "9:00 AM-9:30 AM - Standup (Zoom)"
    assert events[1].all_day is True
    assert format_event(events[1], ZoneInfo("America/New_York")) == "All day - Trash day"


def test_missing_ics_env_becomes_section_notice(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [bot]
        timezone = "America/New_York"

        [sections.calendar]
        type = "calendar"
        source = "ics_url"
        ics_url_env = "BRIEFING_TEST_MISSING_ICS_URL"
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("BRIEFING_TEST_MISSING_ICS_URL", raising=False)
    config = load_config(config_path)

    rendered = render_sections(["calendar"], RunContext(config=config))

    assert rendered[0].title == "Calendar"
    assert "BRIEFING_TEST_MISSING_ICS_URL is not set" in rendered[0].lines[0]
