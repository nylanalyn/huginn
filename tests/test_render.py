from __future__ import annotations

from briefing.render.discord import MESSAGE_BREAK, render_discord_preview
from briefing.render.text import render_briefing
from briefing.sections.base import RenderedSection


def test_text_renderer_is_non_empty() -> None:
    body = render_briefing([RenderedSection(title="Ping", lines=["ok"])])
    assert "Ping" in body
    assert "ok" in body


def test_empty_section_render_is_non_empty() -> None:
    body = render_briefing([RenderedSection(title="Empty", lines=[])])
    assert "(no items)" in body


def test_text_renderer_collects_links_after_sections() -> None:
    body = render_briefing(
        [
            RenderedSection(
                title="News",
                lines=["* Useful summary."],
                link_lines=["https://example.com/story"],
            )
        ]
    )

    assert body == "News\n* Useful summary.\n\nLinks\nhttps://example.com/story\n"


def test_discord_preview_splits_messages_and_separates_links() -> None:
    preview = render_discord_preview(
        [
            RenderedSection(
                title="News",
                lines=["* Useful summary."],
                link_lines=["https://example.com/story"],
            )
        ]
    )

    # The section body and the Links block are delivered as separate messages.
    messages = preview.rstrip("\n").split(MESSAGE_BREAK)
    assert messages == ["News\n* Useful summary.", "Links\nhttps://example.com/story"]


def test_discord_preview_of_empty_is_explicit() -> None:
    assert render_discord_preview([]) == "(empty briefing)\n"
