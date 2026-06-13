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


def test_rss_selection_can_cap_items_per_feed_after_priority_sort(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "briefing.sqlite3"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [sections.news]
        type = "rss"
        max_items = 4
        max_items_per_feed = 2
        since_hours = 24
        feeds = ["high", "mid"]

        [feeds.high]
        name = "High"
        url = "https://example.com/high.xml"
        priority = 9

        [feeds.mid]
        name = "Mid"
        url = "https://example.com/mid.xml"
        priority = 8
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
            title="high newest",
            source="High",
            url="https://example.com/high-1",
            feed_key="high",
            feed_priority=9,
            published_at=now - timedelta(minutes=1),
        ),
        RssItem(
            id=2,
            title="high second",
            source="High",
            url="https://example.com/high-2",
            feed_key="high",
            feed_priority=9,
            published_at=now - timedelta(minutes=2),
        ),
        RssItem(
            id=3,
            title="high third",
            source="High",
            url="https://example.com/high-3",
            feed_key="high",
            feed_priority=9,
            published_at=now - timedelta(minutes=3),
        ),
        RssItem(
            id=4,
            title="mid newest",
            source="Mid",
            url="https://example.com/mid-1",
            feed_key="mid",
            feed_priority=8,
            published_at=now - timedelta(minutes=4),
        ),
        RssItem(
            id=5,
            title="mid second",
            source="Mid",
            url="https://example.com/mid-2",
            feed_key="mid",
            feed_priority=8,
            published_at=now - timedelta(minutes=5),
        ),
    ]

    selected = section.select(items, context)

    assert [item.id for item in selected] == [1, 2, 4, 5]


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


def test_rss_feed_include_filter_accepts_title_or_summary(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "briefing.sqlite3"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [sections.music]
        type = "rss"
        feeds = ["feed"]

        [feeds.feed]
        name = "Feed"
        url = "https://example.com/feed.xml"
        filter_include_keywords = ["gojira", "industrial metal"]
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    section = RssSection("music", config.sections["music"])
    item = section._normalize_entry(
        "feed",
        config.feeds["feed"],
        {
            "title": "New album roundup",
            "link": "https://example.com/story",
            "summary": "Includes industrial metal releases worth hearing.",
        },
        datetime.now(UTC),
    )

    assert item is not None


def test_rss_feed_exclude_filter_rejects_matching_items(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "briefing.sqlite3"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [sections.music]
        type = "rss"
        feeds = ["feed"]

        [feeds.feed]
        name = "Feed"
        url = "https://example.com/feed.xml"
        filter_exclude_keywords = ["funeral doom"]
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    section = RssSection("music", config.sections["music"])
    item = section._normalize_entry(
        "feed",
        config.feeds["feed"],
        {
            "title": "Funeral doom premiere",
            "link": "https://example.com/story",
            "summary": "A very slow one.",
        },
        datetime.now(UTC),
    )

    assert item is None


def test_html_link_feed_extracts_matching_links(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "briefing.sqlite3"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [sections.ai]
        type = "rss"
        feeds = ["anthropic"]

        [feeds.anthropic]
        name = "Anthropic News"
        url = "https://www.anthropic.com/news"
        type = "html_links"
        base_url = "https://www.anthropic.com"
        link_pattern = "^/news/"
        filter_exclude_keywords = ["office opening"]
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    section = RssSection("ai", config.sections["ai"])

    items = section._normalize_html_links(
        "anthropic",
        config.feeds["anthropic"],
        """
        <a href="/news/model-release">Model release</a>
        <a href="/company/about">About</a>
        <a href="/news/office-opening">Office opening</a>
        """,
        Database(db_path),
        fetched_at=datetime.now(UTC),
    )

    assert len(items) == 1
    assert items[0].title == "Model release"
    assert items[0].url == "https://www.anthropic.com/news/model-release"


def test_noaa_alert_feed_filters_area_keywords(tmp_path) -> None:
    import httpx

    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "briefing.sqlite3"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [sections.local]
        type = "rss"
        feeds = ["alerts"]

        [feeds.alerts]
        name = "NOAA Active Florida Alerts"
        url = "https://api.weather.gov/alerts/active?area=FL"
        type = "noaa_alerts"
        filter_area_keywords = ["Hillsborough", "Tampa Bay"]
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    section = RssSection("local", config.sections["local"])
    response = httpx.Response(
        200,
        json={
            "features": [
                {
                    "id": "matching",
                    "properties": {
                        "id": "matching",
                        "headline": "Flood Watch",
                        "areaDesc": "Inland Hillsborough; Coastal Hillsborough",
                        "description": "Heavy rain possible.",
                        "effective": "2026-06-13T14:00:00+00:00",
                    },
                },
                {
                    "id": "other",
                    "properties": {
                        "id": "other",
                        "headline": "Heat Advisory",
                        "areaDesc": "Orange",
                        "description": "Hot weather.",
                    },
                },
            ],
        },
    )

    items = section._normalize_noaa_alerts(
        "alerts",
        config.feeds["alerts"],
        response,
        Database(db_path),
        fetched_at=datetime.now(UTC),
    )

    assert len(items) == 1
    assert items[0].title == "Flood Watch"
    assert "Heavy rain possible." in items[0].body
