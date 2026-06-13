from __future__ import annotations

from pathlib import Path

from briefing.cli import main


def test_dry_run_send_conflict_fails() -> None:
    assert main(["run", "--sections", "ping", "--dry-run", "--send"]) == 2


def test_send_without_webhook_env_fails(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord]
        webhook_url_env = "BRIEFING_TEST_MISSING_WEBHOOK_URL"
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("BRIEFING_TEST_MISSING_WEBHOOK_URL", raising=False)

    assert main(["--config", str(config_path), "run", "--sections", "ping", "--send"]) == 2


def test_invalid_since_fails() -> None:
    assert main(["run", "--sections", "ping", "--since", "nope"]) == 2


def test_health_with_disabled_llm_succeeds(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [llm]
        enabled = false
        """,
        encoding="utf-8",
    )

    assert main(["--config", str(config_path), "health"]) == 0


def test_bot_command_requires_interactive_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [discord.interactive]
        enabled = false
        """,
        encoding="utf-8",
    )

    assert main(["--config", str(config_path), "bot"]) == 2


def test_watch_cli_add_and_list(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "briefing.sqlite3"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"
        """,
        encoding="utf-8",
    )

    assert main(["--config", str(config_path), "watch", "add", "Fedora"]) == 0
    assert main(["--config", str(config_path), "watch", "list"]) == 0

    output = capsys.readouterr().out
    assert "Added watch term: Fedora" in output
    assert "* Fedora" in output


def test_search_cli_items(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "briefing.sqlite3"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [bot]
        database_path = "{db_path}"
        """,
        encoding="utf-8",
    )

    assert main(["--config", str(config_path), "search", "items", "Fedora"]) == 0

    assert "No items found for: Fedora" in capsys.readouterr().out


def test_feeds_list_cli(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [feeds.alpha]
        name = "Alpha Feed"
        url = "https://example.com/feed.xml"
        priority = 7
        """,
        encoding="utf-8",
    )

    assert main(["--config", str(config_path), "feeds", "list"]) == 0

    assert "* alpha: Alpha Feed (priority=7) - https://example.com/feed.xml" in capsys.readouterr().out


def test_summarize_url_cli_rejects_invalid_url(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    assert main(["--config", str(config_path), "summarize", "url", "not-a-url"]) == 2
