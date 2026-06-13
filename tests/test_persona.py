from __future__ import annotations

from pathlib import Path

from briefing.config import load_config
from briefing.llm.prompt import (
    NEUTRAL_PERSONA,
    build_chat_system_prompt,
    build_system_prompt,
    resolve_persona_path,
)
from briefing.sections.base import RunContext


def test_persona_path_loads_from_example_config() -> None:
    config = load_config("config.example.toml")
    assert config.llm.persona_path == "personas/default.md"


def test_persona_prompt_uses_cli_override(tmp_path: Path) -> None:
    persona = tmp_path / "persona.md"
    persona.write_text("Talk like a ship captain.", encoding="utf-8")
    config = load_config("config.example.toml")
    context = RunContext(config=config, profile_name="tech", persona_path=str(persona))

    assert resolve_persona_path(context) == str(persona)
    prompt = build_system_prompt(context)

    assert "Do not invent stories" in prompt
    assert "Talk like a ship captain." in prompt


def test_missing_persona_uses_neutral_voice(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [llm]
        persona_path = "missing-persona.md"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    prompt = build_system_prompt(RunContext(config=config))

    assert NEUTRAL_PERSONA in prompt


def test_chat_prompt_uses_persona_without_summary_json_contract(tmp_path: Path) -> None:
    persona = tmp_path / "persona.md"
    persona.write_text("Speak with dry wit.", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
        [llm]
        persona_path = "{persona}"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    prompt = build_chat_system_prompt(RunContext(config=config))

    assert "You are Huginn" in prompt
    assert "Speak with dry wit." in prompt
    assert "Respond with only a JSON object" not in prompt
    assert "Do not invent stories" not in prompt
