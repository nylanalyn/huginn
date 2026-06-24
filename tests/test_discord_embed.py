from __future__ import annotations

from datetime import UTC, datetime, timedelta

from briefing.render.discord_embed import (
    SECTION_COLORS,
    batch_embeds_for_messages,
    build_briefing_embeds,
)
from briefing.sections.base import RenderedSection, SectionCard

NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def test_news_embed_has_linked_title_summary_and_meta() -> None:
    section = RenderedSection(
        title="News",
        cards=[
            SectionCard(
                title="Big story",
                url="https://example.com/a",
                summary="A concise summary.",
                source="NPR",
                published_at=NOW - timedelta(hours=3),
            )
        ],
    )

    embeds = build_briefing_embeds([section], now=NOW)

    assert len(embeds) == 1
    embed = embeds[0]
    assert embed["title"] == "News"
    assert embed["color"] == SECTION_COLORS["news"]
    assert "**[Big story](https://example.com/a)**" in embed["description"]
    assert "A concise summary." in embed["description"]
    assert "-# NPR · 3h ago" in embed["description"]


def test_section_without_cards_falls_back_to_lines() -> None:
    section = RenderedSection(title="Weather", lines=["High 80F."])

    embeds = build_briefing_embeds([section], now=NOW)

    assert embeds[0]["title"] == "Weather"
    assert embeds[0]["description"] == "High 80F."
    assert embeds[0]["color"] == SECTION_COLORS["weather"]


def test_card_without_url_or_summary_is_plain_title() -> None:
    section = RenderedSection(title="Tech", cards=[SectionCard(title="Headline only")])

    embeds = build_briefing_embeds([section], now=NOW)

    first_line = embeds[0]["description"].splitlines()[0]
    assert first_line == "**Headline only**"


def test_batch_respects_embed_count_limit() -> None:
    embeds = [{"title": f"S{i}", "description": "x"} for i in range(23)]

    batches = batch_embeds_for_messages(embeds)

    assert [len(batch) for batch in batches] == [10, 10, 3]


def test_long_section_description_splits_into_multiple_embeds() -> None:
    cards = [SectionCard(title="t", summary="y" * 2000) for _ in range(4)]
    section = RenderedSection(title="News", cards=cards)

    embeds = build_briefing_embeds([section], now=NOW)

    assert len(embeds) >= 2
    assert all(len(embed["description"]) <= 4096 for embed in embeds)
