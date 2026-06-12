from __future__ import annotations

from .base import Item, RenderedSection, RunContext


class PingSection:
    name = "ping"

    def collect(self, context: RunContext) -> list[Item]:
        return [Item(title="Ping", body="Morning briefing bot is reachable.")]

    def select(self, items: list[Item], context: RunContext) -> list[Item]:
        return items

    def render(self, items: list[Item], context: RunContext) -> RenderedSection:
        lines = [item.body for item in items if item.body]
        return RenderedSection(title="Ping", lines=lines)
