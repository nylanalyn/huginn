from __future__ import annotations

from briefing.discord_webhook import DISCORD_CONTENT_LIMIT, split_sections_for_discord
from briefing.sections.base import RenderedSection


def test_discord_split_keeps_messages_under_limit() -> None:
    sections = [
        RenderedSection(title="One", lines=["a" * 1000]),
        RenderedSection(title="Two", lines=["b" * 1000]),
        RenderedSection(title="Three", lines=["c" * 1000]),
    ]

    messages = split_sections_for_discord(sections)

    assert len(messages) > 1
    assert all(len(message) <= DISCORD_CONTENT_LIMIT for message in messages)


def test_discord_split_handles_single_overlong_line() -> None:
    sections = [RenderedSection(title="Huge", lines=["x" * 4500])]

    messages = split_sections_for_discord(sections)

    assert len(messages) == 3
    assert all(len(message) <= DISCORD_CONTENT_LIMIT for message in messages)
