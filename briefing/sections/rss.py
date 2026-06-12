from __future__ import annotations

import logging
from calendar import timegm
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from briefing.config import FeedConfig, RssSectionConfig
from briefing.db import Database, StoredItem
from briefing.llm.base import LlmProvider, SummaryRequestItem
from briefing.llm.openai_compat import OpenAICompatProvider
from briefing.llm.prompt import build_system_prompt, llm_enabled_for_section, prompt_hash
from briefing.sections.base import Item, RenderedSection, RunContext
from briefing.utils.hashing import dedup_hash_for_entry
from briefing.utils.time import cutoff_from_hours, parse_duration_hours, to_utc_iso, utc_now

LOG = logging.getLogger(__name__)

USER_AGENT = "morning-briefing-bot/0.1 (+local personal briefing bot)"
FEED_TIMEOUT_SECONDS = 15
SUMMARY_LIMIT = 2000


@dataclass(frozen=True)
class RssItem(Item):
    id: int = 0
    guid: str | None = None
    dedup_hash: str = ""
    feed_key: str = ""
    feed_priority: int = 0
    published_at: datetime = datetime.min.replace(tzinfo=UTC)


class RssSection:
    def __init__(self, name: str, section_config: RssSectionConfig) -> None:
        self.name = name
        self.section_config = section_config

    def collect(self, context: RunContext) -> list[RssItem]:
        database = Database(context.config.bot.database_path)
        items: list[RssItem] = []
        for feed_key in self.section_config.feeds:
            feed_config = context.config.feeds[feed_key]
            items.extend(self._fetch_feed(feed_key, feed_config, database))
        return items

    def select(self, items: list[RssItem], context: RunContext) -> list[RssItem]:
        since_hours = self.section_config.since_hours
        if context.since:
            since_hours = parse_duration_hours(context.since)
        max_items = context.max_items or self.section_config.max_items
        cutoff = cutoff_from_hours(utc_now(), since_hours)
        database = Database(context.config.bot.database_path)

        selected: list[RssItem] = []
        seen_candidates: set[tuple[int, str]] = set()
        for item in items:
            candidate_key = (item.id, item.dedup_hash)
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            if item.published_at > cutoff and not database.item_was_used(item.id):
                selected.append(item)
        selected.sort(key=lambda item: (item.feed_priority, item.published_at), reverse=True)
        return selected[:max_items]

    def render(self, items: list[RssItem], context: RunContext) -> RenderedSection:
        lines: list[str] = []
        summaries = self._summaries_for_items(items, context)
        for item in items:
            lines.append(f"* {item.title}")
            summary = summaries.get(item.id)
            if summary:
                lines.append(f"  {summary}")
            lines.append(f"  Source: {item.source} - {item.url}")
        if not lines:
            lines.append("No new items.")
        return RenderedSection(
            title=self.name.title(),
            lines=lines,
            item_ids=[item.id for item in items],
        )

    def _summaries_for_items(self, items: list[RssItem], context: RunContext) -> dict[int, str]:
        if not items or not llm_enabled_for_section(context, self.section_config.use_llm):
            return {}

        database = Database(context.config.bot.database_path)
        system_prompt = build_system_prompt(context)
        cache_key = prompt_hash(system_prompt)
        model = context.config.llm.model
        summaries: dict[int, str] = {}
        missing: list[RssItem] = []

        for item in items:
            cached = database.get_summary(item_id=item.id, model=model, prompt_hash=cache_key)
            if cached:
                summaries[item.id] = cached
            else:
                missing.append(item)

        if not missing:
            return summaries

        try:
            provider = self._build_llm_provider(context)
            request_items = [
                SummaryRequestItem(item_num=index, title=item.title, text=item.body or item.title)
                for index, item in enumerate(missing, start=1)
            ]
            result = provider.summarize(system_prompt=system_prompt, items=request_items)
        except Exception as exc:
            LOG.warning("LLM summaries unavailable for section %s: %s", self.name, exc)
            return summaries

        for index, item in enumerate(missing, start=1):
            summary = result.summaries.get(index, "").strip()
            if not summary:
                continue
            summaries[item.id] = summary
            database.save_summary(
                item_id=item.id,
                model=provider.model,
                prompt_hash=cache_key,
                summary=summary,
            )
        return summaries

    def _build_llm_provider(self, context: RunContext) -> LlmProvider:
        return OpenAICompatProvider(context.config.llm)

    def _fetch_feed(
        self,
        feed_key: str,
        feed_config: FeedConfig,
        database: Database,
    ) -> list[RssItem]:
        headers = {"User-Agent": USER_AGENT}
        state = database.get_feed_state(feed_key)
        if state:
            if state.get("etag"):
                headers["If-None-Match"] = str(state["etag"])
            if state.get("last_modified"):
                headers["If-Modified-Since"] = str(state["last_modified"])

        try:
            response = httpx.get(
                feed_config.url,
                headers=headers,
                timeout=FEED_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            LOG.warning("Feed %s failed: %s", feed_key, exc)
            database.update_feed_state(
                feed_key,
                etag=str((state or {}).get("etag")) if (state or {}).get("etag") else None,
                last_modified=(
                    str((state or {}).get("last_modified"))
                    if (state or {}).get("last_modified")
                    else None
                ),
                status=None,
            )
            return []

        etag = response.headers.get("ETag") or (state or {}).get("etag")
        last_modified = response.headers.get("Last-Modified") or (state or {}).get("last_modified")
        database.update_feed_state(
            feed_key,
            etag=str(etag) if etag else None,
            last_modified=str(last_modified) if last_modified else None,
            status=response.status_code,
        )

        if response.status_code == 304:
            return [
                _from_stored_item(stored, feed_config)
                for stored in database.items_for_feed(feed_key)
            ]
        if response.status_code >= 400:
            LOG.warning("Feed %s returned HTTP %s", feed_key, response.status_code)
            return []

        parsed = feedparser.parse(response.content)
        if getattr(parsed, "bozo", False):
            LOG.warning("Feed %s parsed with warnings: %s", feed_key, parsed.get("bozo_exception"))

        fetched_at = utc_now()
        items: list[RssItem] = []
        for entry in parsed.entries:
            normalized = self._normalize_entry(feed_key, feed_config, entry, fetched_at)
            if normalized:
                stored = database.insert_or_get_item(
                    dedup_hash=normalized.dedup_hash,
                    url=normalized.url or "",
                    guid=normalized.guid,
                    title=normalized.title,
                    source=feed_key,
                    published_at=to_utc_iso(normalized.published_at),
                    fetched_at=to_utc_iso(fetched_at),
                )
                items.append(_with_stored_id(normalized, stored))
        return items

    def _normalize_entry(
        self,
        feed_key: str,
        feed_config: FeedConfig,
        entry: Any,
        fetched_at: datetime,
    ) -> RssItem | None:
        title = str(entry.get("title", "")).strip()
        url = str(entry.get("link", "")).strip()
        if not title or not url:
            return None

        guid = _entry_guid(entry)
        published_at = _entry_datetime(entry, fetched_at)
        summary = _entry_summary(entry)
        dedup_hash = dedup_hash_for_entry(feed_key=feed_key, guid=guid, url=url)
        return RssItem(
            id=0,
            title=title,
            body=summary[:SUMMARY_LIMIT],
            source=feed_config.name,
            url=url,
            guid=guid,
            dedup_hash=dedup_hash,
            feed_key=feed_key,
            feed_priority=feed_config.priority,
            published_at=published_at,
        )


def _with_stored_id(item: RssItem, stored: StoredItem) -> RssItem:
    return RssItem(
        id=stored.id,
        title=stored.title,
        body=item.body,
        source=item.source,
        url=stored.url,
        guid=stored.guid,
        dedup_hash=stored.dedup_hash,
        feed_key=item.feed_key,
        feed_priority=item.feed_priority,
        published_at=datetime.fromisoformat(stored.published_at),
    )


def _from_stored_item(stored: StoredItem, feed_config: FeedConfig) -> RssItem:
    return RssItem(
        id=stored.id,
        title=stored.title,
        source=feed_config.name,
        url=stored.url,
        guid=stored.guid,
        dedup_hash=stored.dedup_hash,
        feed_key=stored.source,
        feed_priority=feed_config.priority,
        published_at=datetime.fromisoformat(stored.published_at),
    )


def _entry_guid(entry: Any) -> str | None:
    for key in ("id", "guid"):
        value = entry.get(key)
        if value:
            return str(value).strip()
    return None


def _entry_summary(entry: Any) -> str:
    for key in ("summary", "description"):
        value = entry.get(key)
        if value:
            return str(value).strip()
    return ""


def _entry_datetime(entry: Any, fallback: datetime) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(timegm(parsed), tz=UTC)

    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            value = parsedate_to_datetime(str(raw))
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        except (TypeError, ValueError, IndexError):
            LOG.warning("Could not parse feed timestamp: %r", raw)

    return fallback
