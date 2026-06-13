from __future__ import annotations

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
