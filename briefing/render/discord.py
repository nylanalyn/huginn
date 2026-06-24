from __future__ import annotations

from briefing.discord_webhook import split_sections_for_discord
from briefing.sections.base import RenderedSection

MESSAGE_BREAK = "\n\n----- message break -----\n\n"


def render_discord_preview(sections: list[RenderedSection]) -> str:
    """Preview a briefing as the sequence of messages Discord would receive.

    Unlike the plain-text render, this applies the real 2000-char chunking and
    trailing "Links" block, with a visible marker between messages.
    """
    messages = split_sections_for_discord(sections)
    if not messages:
        return "(empty briefing)\n"
    return MESSAGE_BREAK.join(messages) + "\n"
