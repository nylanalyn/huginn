from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from briefing.config import AppConfig


@dataclass(frozen=True)
class Item:
    title: str
    body: str = ""
    source: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class RenderedSection:
    title: str
    lines: list[str] = field(default_factory=list)
    link_lines: list[str] = field(default_factory=list)
    item_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class RunContext:
    config: AppConfig
    profile_name: str | None = None
    since: str | None = None
    max_items: int | None = None
    no_llm: bool = False
    format_name: str = "text"
    persona_path: str | None = None


class BriefingSection(Protocol):
    name: str

    def collect(self, context: RunContext) -> list[Item]: ...

    def select(self, items: list[Item], context: RunContext) -> list[Item]: ...

    def render(self, items: list[Item], context: RunContext) -> RenderedSection: ...
