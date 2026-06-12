from __future__ import annotations

from briefing.render.text import render_briefing
from briefing.sections.base import RenderedSection


def render_discord_preview(sections: list[RenderedSection]) -> str:
    return render_briefing(sections)
