from __future__ import annotations

from briefing.sections.weather import summarize_open_meteo


def test_open_meteo_summary_uses_daily_values() -> None:
    summary = summarize_open_meteo(
        {
            "daily": {
                "weather_code": [95],
                "temperature_2m_max": [91.2],
                "temperature_2m_min": [74.4],
                "precipitation_probability_max": [67],
            }
        },
        "imperial",
    )

    assert summary == "Thunderstorms, high 91 deg F, low 74 deg F, precipitation chance 67%."
