from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import httpx

from briefing.actions import feeds_list_text, summarize_url_text
from briefing.config import (
    ConfigError,
    load_config,
    load_env,
    parse_section_names,
    select_sections,
)
from briefing.core import render_sections
from briefing.db import Database
from briefing.discord_bot import run_discord_bot
from briefing.discord_webhook import DiscordWebhookError, DiscordWebhookSender
from briefing.memory import add_watch_text, list_watch_text, search_briefings_text, search_items_text
from briefing.render.discord import render_discord_preview
from briefing.render.text import render_briefing
from briefing.sections.base import RunContext
from briefing.utils.logging import configure_logging
from briefing.utils.time import cutoff_from_hours, parse_duration_hours, utc_now

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

    summarize_parser = subparsers.add_parser("summarize", help="Summarize fetched content")
    summarize_subparsers = summarize_parser.add_subparsers(dest="summarize_command", required=True)
    summarize_url = summarize_subparsers.add_parser("url", help="Summarize a URL")
    summarize_url.add_argument("url")
    summarize_url.set_defaults(func=summarize_command)

    db_parser = subparsers.add_parser("db", help="Database commands")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    db_init = db_subparsers.add_parser("init", help="Initialize database")
    db_init.set_defaults(func=db_command)
    db_status = db_subparsers.add_parser("status", help="Show database status")
    db_status.set_defaults(func=db_command)
    db_prune = db_subparsers.add_parser("prune", help="Prune old database records")
    db_prune.add_argument("--older-than", required=True)
    db_prune.set_defaults(func=db_command)

    health_parser = subparsers.add_parser("health", help="Run health checks")
    health_parser.set_defaults(func=health_command)

    bot_parser = subparsers.add_parser("bot", help="Run the interactive Discord bot")
    bot_parser.set_defaults(func=bot_command)

    search_parser = subparsers.add_parser("search", help="Search saved briefing data")
    search_subparsers = search_parser.add_subparsers(dest="search_command", required=True)
    search_briefings = search_subparsers.add_parser("briefings", help="Search past briefings")
    search_briefings.add_argument("query")
    search_briefings.add_argument("--limit", type=int, default=10)
    search_briefings.set_defaults(func=search_command)
    search_items = search_subparsers.add_parser("items", help="Search seen RSS items")
    search_items.add_argument("query")
    search_items.add_argument("--limit", type=int, default=10)
    search_items.set_defaults(func=search_command)

    watch_parser = subparsers.add_parser("watch", help="Manage topic watch terms")
    watch_subparsers = watch_parser.add_subparsers(dest="watch_command", required=True)
    watch_add = watch_subparsers.add_parser("add", help="Add a watch term")
    watch_add.add_argument("term")
    watch_add.set_defaults(func=watch_command)
    watch_list = watch_subparsers.add_parser("list", help="List watch terms")
    watch_list.set_defaults(func=watch_command)

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
        if config.discord.use_embeds:
            messages = sender.send_section_embeds(rendered)
        else:
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


def feeds_list_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(feeds_list_text(config))
    return 0


def summarize_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    try:
        print(summarize_url_text(config, args.url))
    except (ValueError, httpx.HTTPError) as exc:
        raise ConfigError(f"Could not summarize URL: {exc}") from exc
    return 0


def db_command(args: argparse.Namespace) -> int:
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
    elif args.db_command == "prune":
        try:
            older_than_hours = parse_duration_hours(args.older_than)
        except ValueError as exc:
            raise ConfigError(f"Invalid --older-than value '{args.older_than}': {exc}") from exc
        cutoff = cutoff_from_hours(utc_now(), older_than_hours)
        counts = database.prune_older_than(cutoff.isoformat())
        print(f"pruned records older than {args.older_than}:")
        print(f"briefings: {counts['briefings']}")
        print(f"items: {counts['items']}")
        print(f"conversation_messages: {counts['conversation_messages']}")
    else:
        raise ConfigError(f"Unknown database command: {args.db_command}")
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


def bot_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not config.discord.interactive.enabled:
        raise ConfigError("Discord interactive bot is disabled in config")
    token = os.getenv(config.discord.interactive.token_env)
    if not token:
        raise ConfigError(
            f"Discord bot token environment variable {config.discord.interactive.token_env} is not set"
        )
    asyncio.run(run_discord_bot(config, token))
    return 0


def search_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    database = Database(config.bot.database_path)
    if args.search_command == "briefings":
        print(search_briefings_text(database, args.query, limit=args.limit))
    elif args.search_command == "items":
        print(search_items_text(database, args.query, limit=args.limit))
    else:
        raise ConfigError(f"Unknown search command: {args.search_command}")
    return 0


def watch_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    database = Database(config.bot.database_path)
    if args.watch_command == "add":
        try:
            print(add_watch_text(database, args.term))
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    elif args.watch_command == "list":
        print(list_watch_text(database))
    else:
        raise ConfigError(f"Unknown watch command: {args.watch_command}")
    return 0
