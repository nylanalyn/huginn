from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from briefing.config import load_config
from briefing.db import Database
from briefing.llm.base import SummaryRequestItem, SummaryResult
from briefing.sections.base import RunContext
from briefing.sections.rss import RssItem, RssSection


class FakeProvider:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, *, system_prompt: str, items: list[SummaryRequestItem]) -> SummaryResult:
        self.calls += 1
        return SummaryResult(
            lede="",
            summaries={item.item_num: f"Summary for {item.title}." for item in items},
        )


class StubbedRssSection(RssSection):
    def __init__(self, name, section_config, provider: FakeProvider) -> None:
        super().__init__(name, section_config)
        self.provider = provider

    def _build_llm_provider(self, context: RunContext):
        return self.provider


class FailingProviderSection(RssSection):
    def _build_llm_provider(self, context: RunContext):
        raise AssertionError("provider should not be constructed")


def _config(tmp_path: Path):
    db_path = tmp_path / "briefing.sqlite3"
    persona = tmp_path / "persona.md"
    persona.write_text("Be concise.", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [llm]
        enabled = true
        model = "fake-model"
        persona_path = "{persona}"

        [sections.news]
        type = "rss"
        use_llm = true
        feeds = ["feed"]

        [feeds.feed]
        name = "Feed"
        url = "https://example.com/feed.xml"
        priority = 1
        """,
        encoding="utf-8",
    )
    return load_config(config_path)


def _stored_item(config, title: str = "Story") -> RssItem:
    stored = Database(config.bot.database_path).insert_or_get_item(
        dedup_hash=title,
        url=f"https://example.com/{title}",
        guid=None,
        title=title,
        source="feed",
        published_at=datetime.now(UTC).isoformat(),
        fetched_at=datetime.now(UTC).isoformat(),
    )
    return RssItem(
        id=stored.id,
        title=title,
        body="Feed text",
        source="Feed",
        url=stored.url,
        dedup_hash=stored.dedup_hash,
        feed_key="feed",
        feed_priority=1,
        published_at=datetime.now(UTC),
    )


def test_rss_render_uses_llm_and_caches_summary(tmp_path: Path) -> None:
    config = _config(tmp_path)
    provider = FakeProvider()
    section = StubbedRssSection("news", config.sections["news"], provider)
    item = _stored_item(config)
    context = RunContext(config=config)

    first = section.render([item], context)
    second = section.render([item], context)

    assert provider.calls == 1
    assert "Summary for Story." in "\n".join(first.lines)
    assert "Summary for Story." in "\n".join(second.lines)


def test_no_llm_does_not_construct_provider(tmp_path: Path) -> None:
    config = _config(tmp_path)
    section = FailingProviderSection("news", config.sections["news"])
    item = _stored_item(config)

    rendered = section.render([item], RunContext(config=config, no_llm=True))

    assert "Source: Feed" in "\n".join(rendered.lines)
