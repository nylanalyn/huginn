from __future__ import annotations

from pathlib import Path

from briefing.config import load_config
from briefing.discord_bot import InteractionIdentity, interaction_allowed


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
