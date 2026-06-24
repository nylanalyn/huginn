from __future__ import annotations

from datetime import UTC, datetime, timedelta

from briefing.config import AppConfig
from briefing.db import Database


def search_briefings_text(database: Database, query: str, *, limit: int = 10) -> str:
    rows = database.search_briefings(query, limit=limit)
    if not rows:
        return f"No briefings found for: {query}"
    lines = [f"Briefings matching '{query}':"]
    for row in rows:
        snippet = _snippet(str(row["body"]), query)
        profile = row["profile"] or "-"
        lines.append(f"* #{row['id']} {row['created_at']} profile={profile} sections={row['sections']}")
        lines.append(f"  {snippet}")
    return "\n".join(lines)


def search_items_text(database: Database, query: str, *, limit: int = 10) -> str:
    rows = database.search_items(query, limit=limit)
    if not rows:
        return f"No items found for: {query}"
    lines = [f"Items matching '{query}':"]
    for row in rows:
        lines.append(f"* #{row['id']} {row['title']}")
        lines.append(f"  Source: {row['source']} - {row['url']}")
    return "\n".join(lines)


def add_watch_text(database: Database, term: str) -> str:
    added = database.add_watch_term(term)
    normalized = " ".join(term.strip().split())
    if added:
        return f"Added watch term: {normalized}"
    return f"Watch term already exists: {normalized}"


def list_watch_text(database: Database) -> str:
    rows = database.list_watch_terms()
    if not rows:
        return "No watch terms configured."
    lines = ["Watch terms:"]
    lines.extend(f"* {row['term']}" for row in rows)
    return "\n".join(lines)


def remember_fact_text(config: AppConfig, database: Database, *, user_id: int, fact: str) -> str:
    if not config.discord.interactive.remembered_facts_enabled:
        return "Remembered facts are disabled."
    added = database.add_remembered_fact(user_id=user_id, fact=fact)
    normalized = " ".join(fact.strip().split())
    if added:
        return f"Remembered: {normalized}"
    return f"Already remembered: {normalized}"


def list_remembered_facts_text(config: AppConfig, database: Database, *, user_id: int) -> str:
    if not config.discord.interactive.remembered_facts_enabled:
        return "Remembered facts are disabled."
    rows = database.list_remembered_facts(
        user_id=user_id,
        limit=config.discord.interactive.remembered_facts_max_items,
    )
    if not rows:
        return "No remembered facts."
    lines = ["Remembered facts:"]
    lines.extend(f"* {row['fact']}" for row in rows)
    return "\n".join(lines)


def clear_remembered_facts_text(config: AppConfig, database: Database, *, user_id: int) -> str:
    if not config.discord.interactive.remembered_facts_enabled:
        return "Remembered facts are disabled."
    removed = database.clear_remembered_facts(user_id=user_id)
    return f"Cleared {removed} remembered fact(s)."


def conversation_context_text(
    config: AppConfig,
    database: Database,
    *,
    guild_id: int | None,
    channel_id: int,
    user_id: int,
) -> str:
    parts: list[str] = []
    if config.discord.interactive.remembered_facts_enabled:
        facts = database.list_remembered_facts(
            user_id=user_id,
            limit=config.discord.interactive.remembered_facts_max_items,
        )
        if facts:
            parts.append("Remembered facts explicitly approved by the user:")
            parts.extend(f"- {row['fact']}" for row in facts)

    if config.discord.interactive.conversation_memory_enabled:
        since = datetime.now(UTC) - timedelta(
            minutes=config.discord.interactive.conversation_memory_max_age_minutes
        )
        messages = database.recent_conversation_messages(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            since_iso=since.isoformat(),
            limit=config.discord.interactive.conversation_memory_max_messages,
        )
        if messages:
            parts.append("Recent opt-in conversation context:")
            token_budget = config.discord.interactive.conversation_memory_max_tokens
            running_len = len("\n".join(parts))
            for row in messages:
                role = str(row["role"])
                content = _collapse(str(row["content"]))
                if max(1, (running_len + len(content)) // 4) > token_budget:
                    break
                line = f"- {role}: {content}"
                parts.append(line)
                running_len += len(line) + 1  # +1 for the joining newline

    return "\n".join(parts)


def retrieval_context_text(config: AppConfig, database: Database, message: str) -> str:
    if not config.discord.interactive.retrieval_context_enabled:
        return ""
    query = _explicit_retrieval_query(message)
    if not query:
        return ""
    limit = config.discord.interactive.retrieval_context_limit
    parts: list[str] = [f"Retrieved local context for query '{query}':"]
    briefings = database.search_briefings(query, limit=limit)
    if briefings:
        parts.append("Past briefings:")
        for row in briefings:
            parts.append(f"- #{row['id']} {row['created_at']}: {_snippet(str(row['body']), query)}")
    items = database.search_items(query, limit=limit)
    if items:
        parts.append("Seen items:")
        for row in items:
            parts.append(f"- {row['title']} ({row['source']}) {row['url']}")
    if len(parts) == 1:
        return ""
    return "\n".join(parts)


def _explicit_retrieval_query(message: str) -> str:
    normalized = _collapse(message)
    lower = normalized.lower()
    triggers = ("past briefing", "past briefings", "previous briefing", "previous briefings", "seen item", "seen items")
    if not any(trigger in lower for trigger in triggers):
        return ""
    marker = " about "
    index = lower.rfind(marker)
    if index < 0:
        return ""
    return normalized[index + len(marker) :].strip(" ?.")


def _snippet(body: str, query: str, *, radius: int = 90) -> str:
    lower_body = body.lower()
    lower_query = query.lower()
    index = lower_body.find(lower_query)
    if index < 0:
        return _collapse(body)[: radius * 2].rstrip()
    start = max(0, index - radius)
    end = min(len(body), index + len(query) + radius)
    prefix = "..." if start else ""
    suffix = "..." if end < len(body) else ""
    return prefix + _collapse(body[start:end]) + suffix


def _collapse(value: str) -> str:
    return " ".join(value.split())
