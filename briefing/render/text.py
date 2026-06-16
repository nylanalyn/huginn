from __future__ import annotations

from briefing.sections.base import RenderedSection


def render_briefing(sections: list[RenderedSection]) -> str:
    chunks: list[str] = []
    link_lines: list[str] = []
    for section in sections:
        body = "\n".join(section.lines) if section.lines else "(no items)"
        chunks.append(f"{section.title}\n{body}")
        link_lines.extend(section.link_lines)
    if link_lines:
        chunks.append("Links\n" + "\n".join(link_lines))
    return "\n\n".join(chunks).strip() + "\n"
