from __future__ import annotations

import logging

from briefing.config import CalendarSectionConfig, RssSectionConfig, WeatherSectionConfig
from briefing.sections.base import RenderedSection, RunContext
from briefing.sections.calendar import CalendarSection
from briefing.sections.ping import PingSection
from briefing.sections.rss import RssSection
from briefing.sections.weather import WeatherSection

LOG = logging.getLogger(__name__)


def render_sections(section_names: list[str], context: RunContext) -> list[RenderedSection]:
    rendered: list[RenderedSection] = []
    for section_name in section_names:
        try:
            section = build_section(section_name, context)
            items = section.collect(context)
            selected = section.select(items, context)
            rendered.append(section.render(selected, context))
        except Exception as exc:
            LOG.warning("Section %s failed: %s", section_name, exc)
            LOG.debug("Section %s traceback", section_name, exc_info=True)
            rendered.append(
                RenderedSection(
                    title=section_name.title(),
                    lines=[f"Section failed: {exc}"],
                )
            )
    return rendered


def build_section(
    name: str,
    context: RunContext | None = None,
) -> PingSection | RssSection | WeatherSection | CalendarSection | PlaceholderSection:
    if name == "ping":
        return PingSection()
    if context is not None:
        section_config = context.config.sections.get(name)
        if isinstance(section_config, RssSectionConfig):
            return RssSection(name, section_config)
        if isinstance(section_config, WeatherSectionConfig):
            return WeatherSection(section_config)
        if isinstance(section_config, CalendarSectionConfig):
            return CalendarSection(section_config)
    return PlaceholderSection(name)


class PlaceholderSection:
    def __init__(self, name: str) -> None:
        self.name = name

    def collect(self, context: RunContext) -> list:
        return []

    def select(self, items: list, context: RunContext) -> list:
        return items

    def render(self, items: list, context: RunContext) -> RenderedSection:
        return RenderedSection(
            title=self.name.title(),
            lines=[f"{self.name} section is configured; implementation arrives in a later stage."],
        )
