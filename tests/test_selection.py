from __future__ import annotations

import pytest

from briefing.config import ConfigError, load_config, select_sections


def test_default_run_selects_ping() -> None:
    config = load_config("config.example.toml")
    assert select_sections(config, None, None) == ["ping"]


def test_profile_selects_configured_sections() -> None:
    config = load_config("config.example.toml")
    assert select_sections(config, "tech", None) == ["weather", "calendar", "tech"]


def test_comma_sections_select_multiple_sections() -> None:
    config = load_config("config.example.toml")
    assert select_sections(config, None, ["news", "tech"]) == ["news", "tech"]


def test_profile_and_sections_are_mutually_exclusive() -> None:
    config = load_config("config.example.toml")
    with pytest.raises(ConfigError, match="either --profile or --sections"):
        select_sections(config, "daily", ["ping"])
