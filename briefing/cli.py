from __future__ import annotations

import argparse
import logging
import os
import sys

import httpx

from briefing.config import (
    CalendarSectionConfig,
    ConfigError,
    RssSectionConfig,
    WeatherSectionConfig,
    load_config,
    load_env,
    parse_section_names,
    select_sections,
)
from briefing.db import Database
from briefing.discord_webhook import DiscordWebhookError, DiscordWebhookSender
from briefing.render.discord import render_discord_preview
from briefing.render.text import render_briefing
from briefing.sections.base import RenderedSection, RunContext
from briefing.sections.calendar import CalendarSection
from briefing.sections.ping import PingSection
from briefing.sections.rss import RssSection
from briefing.sections.weather import WeatherSection
from briefing.utils.logging import configure_logging
from briefing.utils.time import parse_duration_hours

LOG = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)
    load_env()

    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except DiscordWebhookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="briefing")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Build a briefing")
    run_parser.add_argument("--profile", help="Profile name from config")
    run_parser.add_argument("--sections", help="Comma-separated section names")
    run_parser.add_argument("--since", help="Override section since window, e.g. 12h")
    run_parser.add_argument("--max-items", type=int, help="Override section max item count")
    run_parser.add_argument("--no-llm", action="store_true", help="Disable LLM summaries")
    run_parser.add_argument("--dry-run", action="store_true", help="Print without sending")
    run_parser.add_argument("--send", action="store_true", help="Send via Discord webhook")
    run_parser.add_argument("--persona", help="Persona markdown path override")
    run_parser.add_argument("--format", choices=["text", "discord"], default="text")
    run_parser.set_defaults(func=run_command)

    feeds_parser = subparsers.add_parser("feeds", help="Feed commands")
    feeds_subparsers = feeds_parser.add_subparsers(dest="feeds_command", required=True)
    feeds_list = feeds_subparsers.add_parser("list", help="List configured feeds")
    feeds_list.set_defaults(func=feeds_list_command)

    db_parser = subparsers.add_parser("db", help="Database commands")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    db_init = db_subparsers.add_parser("init", help="Initialize database")
    db_init.set_defaults(func=db_placeholder_command)
    db_status = db_subparsers.add_parser("status", help="Show database status")
    db_status.set_defaults(func=db_placeholder_command)
    db_prune = db_subparsers.add_parser("prune", help="Prune old database records")
    db_prune.add_argument("--older-than", required=True)
    db_prune.set_defaults(func=db_placeholder_command)

    health_parser = subparsers.add_parser("health", help="Run health checks")
    health_parser.set_defaults(func=health_command)

    return parser


def run_command(args: argparse.Namespace) -> int:
    if args.dry_run and args.send:
        raise ConfigError("--dry-run and --send cannot be used together")

    config = load_config(args.config)
    if args.since:
        try:
            parse_duration_hours(args.since)
        except ValueError as exc:
            raise ConfigError(f"Invalid --since value '{args.since}': {exc}") from exc
    section_names = select_sections(config, args.profile, parse_section_names(args.sections))
    context = RunContext(
        config=config,
        profile_name=args.profile,
        since=args.since,
        max_items=args.max_items,
        no_llm=args.no_llm,
        format_name=args.format,
        persona_path=args.persona,
    )
    rendered = render_sections(section_names, context)
    body = render_discord_preview(rendered) if args.format == "discord" else render_briefing(rendered)

    if args.send:
        webhook_url = os.getenv(config.discord.webhook_url_env)
        if not webhook_url:
            raise ConfigError(
                f"Discord webhook environment variable {config.discord.webhook_url_env} is not set"
            )
        sender = DiscordWebhookSender(webhook_url=webhook_url)
        messages = sender.send_sections(rendered)
        Database(config.bot.database_path).record_sent_briefing(
            profile=args.profile,
            section_names=section_names,
            rendered_sections=rendered,
            body=body,
        )
        print(f"sent {len(messages)} Discord message(s)")
    else:
        print(body, end="")

    return 0


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


def feeds_list_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    for key, feed in sorted(config.feeds.items()):
        print(f"{key}\t{feed.name}\tpriority={feed.priority}\t{feed.url}")
    return 0


def db_placeholder_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    database = Database(config.bot.database_path)
    if args.db_command == "init":
        database.init()
        print(f"initialized database: {config.bot.database_path}")
    elif args.db_command == "status":
        database.init()
        print(f"database_path: {config.bot.database_path}")
        print(f"items: {database.count_items()}")
        print(f"briefings: {database.count_briefings()}")
    else:
        print("Database prune is implemented in a later stage.")
    return 0


def health_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    database = Database(config.bot.database_path)
    database.init()
    print(f"config: ok")
    print(f"database_path: {config.bot.database_path}")
    states = database.feed_states(list(config.feeds))
    if states:
        print("feed states:")
        for state in states:
            print(
                f"- {state['feed_key']}: status={state['last_status']} "
                f"last_fetched={state['last_fetched']}"
            )
    else:
        print("feed states: none fetched yet")
    if not config.llm.enabled:
        print("llm: disabled")
        return 0
    try:
        response = httpx.get(
            config.llm.base_url.rstrip("/") + "/models",
            timeout=min(config.llm.timeout_seconds, 10),
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"llm: failed ({exc})")
        return 1
    print("llm: ok")
    return 0
