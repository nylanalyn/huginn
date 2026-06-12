from __future__ import annotations

from pathlib import Path

import pytest

from briefing.config import ConfigError, load_config, select_sections


def test_example_config_loads() -> None:
    config = load_config("config.example.toml")
    assert config.profiles["daily"].sections == ["weather", "calendar", "news"]


def test_dangling_profile_section_fails(tmp_path: Path) -> None:
    config_path = tmp_path / "broken.toml"
    config_path.write_text(
        """
        [profiles.daily]
        sections = ["missing"]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="undefined section 'missing'"):
        load_config(config_path)


def test_dangling_rss_feed_fails(tmp_path: Path) -> None:
    config_path = tmp_path / "broken.toml"
    config_path.write_text(
        """
        [sections.news]
        type = "rss"
        feeds = ["missing"]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="undefined feed 'missing'"):
        load_config(config_path)


def test_ping_section_is_builtin() -> None:
    config = load_config("config.example.toml")
    assert select_sections(config, None, ["ping"]) == ["ping"]
