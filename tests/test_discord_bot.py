from __future__ import annotations

from pathlib import Path

from briefing.config import load_config
from briefing.db import Database
from briefing.discord_bot import (
    CHAT_UNAVAILABLE_MESSAGE,
    BriefingDiscordBot,
    InteractionIdentity,
    _command_reply_chunks,
    interaction_allowed,
)
from briefing.sections.base import RenderedSection, SectionCard


class _FakePerms:
    def __init__(self, embed_links: bool) -> None:
        self.embed_links = embed_links


class _FakeGuild:
    me = object()


class _FakeChannel:
    def __init__(self, embed_links: bool) -> None:
        self.guild = _FakeGuild()
        self._embed_links = embed_links

    def permissions_for(self, member):
        del member
        return _FakePerms(self._embed_links)


def _embeds_config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord]
        use_embeds = true

        [llm]
        enabled = true
        """,
        encoding="utf-8",
    )
    return load_config(config_path)


def _news_rendered() -> list[RenderedSection]:
    return [
        RenderedSection(
            title="News",
            cards=[SectionCard(title="Story", url="https://example.com/x", summary="A summary.")],
        )
    ]


class FakeChatProvider:
    model = "fake"

    def __init__(self) -> None:
        self.calls = []

    def chat(self, *, system_prompt, message, max_tokens=None, temperature=None) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "message": message,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return "persona reply"


class StubbedDiscordBot(BriefingDiscordBot):
    def __init__(self, config, provider: FakeChatProvider) -> None:
        self.provider = provider
        super().__init__(config)

    def _build_llm_provider(self):
        return self.provider


def test_interaction_allowed_respects_guild_channel_and_user(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord.interactive]
        enabled = true
        allowed_guild_ids = [1]
        allowed_channel_ids = [2]
        allowed_user_ids = [3]
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    assert interaction_allowed(config, InteractionIdentity(guild_id=1, channel_id=2, user_id=3))
    assert not interaction_allowed(config, InteractionIdentity(guild_id=9, channel_id=2, user_id=3))
    assert not interaction_allowed(config, InteractionIdentity(guild_id=1, channel_id=9, user_id=3))
    assert not interaction_allowed(config, InteractionIdentity(guild_id=1, channel_id=2, user_id=9))


def test_empty_allowed_users_allows_any_user_in_allowed_context(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord.interactive]
        enabled = true
        allowed_guild_ids = [1]
        allowed_channel_ids = [2]
        allowed_user_ids = []
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    assert interaction_allowed(config, InteractionIdentity(guild_id=1, channel_id=2, user_id=999))


def test_mention_chat_uses_provider_and_interactive_limits(tmp_path: Path) -> None:
    persona = tmp_path / "persona.md"
    persona.write_text("Answer like Huginn.", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [discord.interactive]
        enabled = true
        mention_chat_enabled = true
        mention_chat_max_tokens = 321
        mention_chat_temperature = 0.6

        [llm]
        enabled = true
        persona_path = "{persona}"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    provider = FakeChatProvider()
    bot = StubbedDiscordBot(config, provider)

    assert bot._chat_for_interaction("say hello") == "persona reply"
    assert provider.calls[0]["message"] == "say hello"
    assert provider.calls[0]["max_tokens"] == 321
    assert provider.calls[0]["temperature"] == 0.6
    assert "Answer like Huginn." in provider.calls[0]["system_prompt"]
    assert "Respond with only a JSON object" not in provider.calls[0]["system_prompt"]


def test_mention_chat_disabled_llm_returns_fallback(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [llm]
        enabled = false
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    bot = StubbedDiscordBot(config, FakeChatProvider())

    assert bot._chat_for_interaction("say hello") == CHAT_UNAVAILABLE_MESSAGE


def test_empty_text_command_result_is_explicit() -> None:
    assert _command_reply_chunks("") == ["(empty result)"]


def test_text_command_reply_has_no_section_header() -> None:
    assert _command_reply_chunks("Watch terms:\n* gojira") == ["Watch terms:\n* gojira"]


def test_briefing_uses_embeds_when_permission_present(tmp_path: Path) -> None:
    bot = StubbedDiscordBot(_embeds_config(tmp_path), FakeChatProvider())

    payloads = bot._briefing_payloads(_news_rendered(), channel=_FakeChannel(embed_links=True))

    assert payloads and all("embeds" in payload for payload in payloads)


def test_briefing_falls_back_to_text_without_embed_permission(tmp_path: Path) -> None:
    bot = StubbedDiscordBot(_embeds_config(tmp_path), FakeChatProvider())

    payloads = bot._briefing_payloads(_news_rendered(), channel=_FakeChannel(embed_links=False))

    assert payloads
    assert all("content" in payload and "embeds" not in payload for payload in payloads)


def test_briefing_uses_embeds_in_dm_context(tmp_path: Path) -> None:
    bot = StubbedDiscordBot(_embeds_config(tmp_path), FakeChatProvider())

    # channel=None models a DM/unknown channel: embeds are assumed allowed.
    payloads = bot._briefing_payloads(_news_rendered(), channel=None)

    assert payloads and all("embeds" in payload for payload in payloads)


def test_mention_chat_includes_and_records_opt_in_memory(tmp_path: Path) -> None:
    db_path = tmp_path / "briefing.sqlite3"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"

        [discord.interactive]
        enabled = true
        mention_chat_enabled = true
        conversation_memory_enabled = true
        remembered_facts_enabled = true

        [llm]
        enabled = true
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    database = Database(db_path)
    database.add_remembered_fact(user_id=3, fact="likes concise answers")
    provider = FakeChatProvider()
    bot = StubbedDiscordBot(config, provider)

    response = bot._chat_for_interaction(
        "say hello",
        InteractionIdentity(guild_id=1, channel_id=2, user_id=3),
    )

    assert response == "persona reply"
    assert "likes concise answers" in provider.calls[0]["system_prompt"]
    rows = database.recent_conversation_messages(
        guild_id=1,
        channel_id=2,
        user_id=3,
        since_iso="1970-01-01T00:00:00+00:00",
        limit=10,
    )
    assert [row["role"] for row in rows] == ["user", "assistant"]
