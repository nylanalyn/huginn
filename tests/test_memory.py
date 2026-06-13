from __future__ import annotations

from datetime import UTC, datetime

from briefing.config import load_config
from briefing.db import Database
from briefing.memory import (
    add_watch_text,
    conversation_context_text,
    list_remembered_facts_text,
    list_watch_text,
    remember_fact_text,
    retrieval_context_text,
    search_briefings_text,
    search_items_text,
)
from briefing.sections.base import RenderedSection


def test_watch_terms_are_persistent_and_deduped(tmp_path) -> None:
    database = Database(tmp_path / "briefing.sqlite3")

    assert add_watch_text(database, "  Fedora   Linux ") == "Added watch term: Fedora Linux"
    assert add_watch_text(database, "Fedora Linux") == "Watch term already exists: Fedora Linux"

    assert list_watch_text(database) == "Watch terms:\n* Fedora Linux"


def test_search_items_finds_seen_titles(tmp_path) -> None:
    database = Database(tmp_path / "briefing.sqlite3")
    database.insert_or_get_item(
        dedup_hash="fedora",
        url="https://example.com/fedora",
        guid=None,
        title="Fedora releases a new version",
        source="feed",
        published_at=datetime.now(UTC).isoformat(),
        fetched_at=datetime.now(UTC).isoformat(),
    )

    result = search_items_text(database, "Fedora")

    assert "Fedora releases a new version" in result
    assert "https://example.com/fedora" in result


def test_search_briefings_finds_recorded_body(tmp_path) -> None:
    database = Database(tmp_path / "briefing.sqlite3")
    database.record_sent_briefing(
        profile="daily",
        section_names=["news"],
        rendered_sections=[RenderedSection(title="News")],
        body="News\nFedora had a busy release morning.",
    )

    result = search_briefings_text(database, "Fedora")

    assert "Briefings matching 'Fedora':" in result
    assert "profile=daily" in result
    assert "Fedora had a busy release morning" in result


def test_remembered_facts_are_disabled_by_default(tmp_path) -> None:
    config = load_config(tmp_path / "missing.toml")
    database = Database(tmp_path / "briefing.sqlite3")

    assert remember_fact_text(config, database, user_id=1, fact="likes Fedora") == "Remembered facts are disabled."


def test_remembered_facts_require_explicit_enablement(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord.interactive]
        remembered_facts_enabled = true
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    database = Database(tmp_path / "briefing.sqlite3")

    assert remember_fact_text(config, database, user_id=1, fact="likes Fedora") == "Remembered: likes Fedora"
    assert "likes Fedora" in list_remembered_facts_text(config, database, user_id=1)


def test_conversation_context_uses_enabled_recent_messages_and_facts(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord.interactive]
        conversation_memory_enabled = true
        conversation_memory_max_messages = 4
        conversation_memory_max_age_minutes = 60
        remembered_facts_enabled = true
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    database = Database(tmp_path / "briefing.sqlite3")
    database.add_remembered_fact(user_id=1, fact="likes concise answers")
    database.add_conversation_message(guild_id=2, channel_id=3, user_id=1, role="user", content="hello")
    database.add_conversation_message(guild_id=2, channel_id=3, user_id=1, role="assistant", content="hi")

    context = conversation_context_text(config, database, guild_id=2, channel_id=3, user_id=1)

    assert "likes concise answers" in context
    assert "- user: hello" in context
    assert "- assistant: hi" in context


def test_conversation_context_respects_token_budget(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord.interactive]
        conversation_memory_enabled = true
        conversation_memory_max_messages = 4
        conversation_memory_max_tokens = 12
        conversation_memory_max_age_minutes = 60
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    database = Database(tmp_path / "briefing.sqlite3")
    database.add_conversation_message(guild_id=2, channel_id=3, user_id=1, role="user", content="short")
    database.add_conversation_message(
        guild_id=2,
        channel_id=3,
        user_id=1,
        role="assistant",
        content="this response is intentionally far too long for the tiny context budget",
    )

    context = conversation_context_text(config, database, guild_id=2, channel_id=3, user_id=1)

    assert "- user: short" in context
    assert "far too long" not in context


def test_retrieval_context_requires_explicit_trigger(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord.interactive]
        retrieval_context_enabled = true
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    database = Database(tmp_path / "briefing.sqlite3")
    database.record_sent_briefing(
        profile="daily",
        section_names=["news"],
        rendered_sections=[RenderedSection(title="News")],
        body="News\nFedora had a busy release morning.",
    )

    assert retrieval_context_text(config, database, "tell me something") == ""
    context = retrieval_context_text(config, database, "what did past briefings say about Fedora?")

    assert "Retrieved local context for query 'Fedora'" in context
    assert "Fedora had a busy release morning" in context
