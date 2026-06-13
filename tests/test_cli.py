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
