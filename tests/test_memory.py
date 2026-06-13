from __future__ import annotations

from datetime import UTC, datetime

from briefing.db import Database
from briefing.memory import add_watch_text, list_watch_text, search_briefings_text, search_items_text
from briefing.sections.base import RenderedSection


def test_watch_terms_are_persistent_and_deduped(tmp_path) -> None:
    database = Database(tmp_path / "briefing.sqlite3")

    assert add_watch_text(database, "  Fedora   Linux ") == "Added watch term: Fedora Linux"
    assert add_watch_text(database, "Fedora Linux") == "Watch term already exists: Fedora Linux"

    assert list_watch_text(database) == "Watch terms:\n* Fedora Linux"


def test_search_items_finds_seen_titles(tmp_path) -> None:
    database = Database(tmp_path / "briefing.sqlite3")
    database.insert_or_get_item(
        dedup_hash="fedora",
        url="https://example.com/fedora",
        guid=None,
        title="Fedora releases a new version",
        source="feed",
        published_at=datetime.now(UTC).isoformat(),
        fetched_at=datetime.now(UTC).isoformat(),
    )

    result = search_items_text(database, "Fedora")

    assert "Fedora releases a new version" in result
    assert "https://example.com/fedora" in result


def test_search_briefings_finds_recorded_body(tmp_path) -> None:
    database = Database(tmp_path / "briefing.sqlite3")
    database.record_sent_briefing(
        profile="daily",
        section_names=["news"],
        rendered_sections=[RenderedSection(title="News")],
        body="News\nFedora had a busy release morning.",
    )

    result = search_briefings_text(database, "Fedora")

    assert "Briefings matching 'Fedora':" in result
    assert "profile=daily" in result
    assert "Fedora had a busy release morning" in result
