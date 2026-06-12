from __future__ import annotations

from datetime import UTC, datetime, timedelta

from briefing.config import load_config
from briefing.db import Database
from briefing.sections.base import RenderedSection, RunContext
from briefing.sections.rss import RssItem, RssSection
from briefing.utils.hashing import dedup_hash_for_entry


def test_tracking_parameter_variants_dedupe() -> None:
    first = dedup_hash_for_entry(
        feed_key="a",
        guid=None,
        url="https://Example.com/story?utm_source=x&at_medium=RSS&id=1#section",
    )
    second = dedup_hash_for_entry(
        feed_key="b",
        guid=None,
        url="https://example.com/story?id=1&utm_campaign=y",
    )

    assert first == second


def test_opaque_guid_is_feed_scoped() -> None:
    first = dedup_hash_for_entry(feed_key="a", guid="123", url="https://example.com/a")
    second = dedup_hash_for_entry(feed_key="b", guid="123", url="https://example.com/b")

    assert first != second


def test_permalink_guid_dedupes_across_feeds() -> None:
    first = dedup_hash_for_entry(
        feed_key="a",
        guid="https://example.com/story?utm_source=x",
        url="https://other.example/a",
    )
    second = dedup_hash_for_entry(
        feed_key="b",
        guid="https://example.com/story",
        url="https://other.example/b",
    )

    assert first == second


def test_rss_selection_respects_priority_since_and_max_items(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "briefing.sqlite3"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [sections.news]
        type = "rss"
        max_items = 2
        since_hours = 24
        feeds = ["high", "low"]

        [feeds.high]
        name = "High"
        url = "https://example.com/high.xml"
        priority = 9

        [feeds.low]
        name = "Low"
        url = "https://example.com/low.xml"
        priority = 1
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    context = RunContext(config=config)
    section = RssSection("news", config.sections["news"])
    now = datetime.now(UTC)
    items = [
        RssItem(
            id=1,
            title="low recent",
            source="Low",
            url="https://example.com/1",
            feed_priority=1,
            published_at=now - timedelta(hours=1),
        ),
        RssItem(
            id=2,
            title="high old",
            source="High",
            url="https://example.com/2",
            feed_priority=9,
            published_at=now - timedelta(days=2),
        ),
        RssItem(
            id=3,
            title="high recent",
            source="High",
            url="https://example.com/3",
            feed_priority=9,
            published_at=now - timedelta(hours=3),
        ),
        RssItem(
            id=4,
            title="high newest",
            source="High",
            url="https://example.com/4",
            feed_priority=9,
            published_at=now - timedelta(hours=1),
        ),
    ]

    selected = section.select(items, context)

    assert [item.id for item in selected] == [4, 3]


def test_rss_selection_cli_overrides_since_and_max_items(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "briefing.sqlite3"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [sections.news]
        type = "rss"
        max_items = 10
        since_hours = 48
        feeds = ["feed"]

        [feeds.feed]
        name = "Feed"
        url = "https://example.com/feed.xml"
        priority = 1
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    context = RunContext(config=config, since="2h", max_items=1)
    section = RssSection("news", config.sections["news"])
    now = datetime.now(UTC)
    items = [
        RssItem(
            id=1,
            title="old but inside config window",
            source="Feed",
            url="https://example.com/old",
            feed_priority=1,
            published_at=now - timedelta(hours=12),
        ),
        RssItem(
            id=2,
            title="recent",
            source="Feed",
            url="https://example.com/recent",
            feed_priority=1,
            published_at=now - timedelta(minutes=30),
        ),
        RssItem(
            id=3,
            title="also recent",
            source="Feed",
            url="https://example.com/also-recent",
            feed_priority=1,
            published_at=now - timedelta(minutes=45),
        ),
    ]

    selected = section.select(items, context)

    assert [item.id for item in selected] == [2]


def test_rss_selection_skips_used_items(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "briefing.sqlite3"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [sections.news]
        type = "rss"
        max_items = 5
        since_hours = 24
        feeds = ["feed"]

        [feeds.feed]
        name = "Feed"
        url = "https://example.com/feed.xml"
        priority = 1
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    database = Database(db_path)
    stored = database.insert_or_get_item(
        dedup_hash="abc",
        url="https://example.com/used",
        guid=None,
        title="Used",
        source="feed",
        published_at=datetime.now(UTC).isoformat(),
        fetched_at=datetime.now(UTC).isoformat(),
    )
    database.record_sent_briefing(
        profile=None,
        section_names=["news"],
        rendered_sections=[RenderedSection(title="News", item_ids=[stored.id])],
        body="News",
    )
    item = RssItem(
        id=stored.id,
        title="Used",
        source="Feed",
        url="https://example.com/used",
        feed_priority=1,
        published_at=datetime.now(UTC),
    )

    section = RssSection("news", config.sections["news"])
    assert section.select([item], RunContext(config=config)) == []
