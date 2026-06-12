from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from briefing.config import WeatherSectionConfig
from briefing.sections.base import RenderedSection, RunContext

LOG = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_TIMEOUT_SECONDS = 15

WEATHER_CODES = {
    0: "clear",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "light freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "light snow showers",
    86: "snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "severe thunderstorms with hail",
}


@dataclass(frozen=True)
class WeatherReport:
    summary: str


class WeatherSection:
    name = "weather"

    def __init__(self, section_config: WeatherSectionConfig) -> None:
        self.section_config = section_config

    def collect(self, context: RunContext) -> list[WeatherReport]:
        if self.section_config.provider != "open-meteo":
            raise ValueError(f"Unsupported weather provider: {self.section_config.provider}")

        response = httpx.get(
            OPEN_METEO_URL,
            params=_open_meteo_params(self.section_config, context.config.bot.timezone),
            timeout=WEATHER_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return [WeatherReport(summary=summarize_open_meteo(response.json(), self.section_config.units))]

    def select(self, items: list[WeatherReport], context: RunContext) -> list[WeatherReport]:
        return items

    def render(self, items: list[WeatherReport], context: RunContext) -> RenderedSection:
        lines = [item.summary for item in items] or ["No weather data."]
        return RenderedSection(title="Weather", lines=lines)


def _open_meteo_params(config: WeatherSectionConfig, timezone: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "latitude": config.latitude,
        "longitude": config.longitude,
        "timezone": timezone,
        "forecast_days": 1,
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
            ]
        ),
    }
    if config.units == "imperial":
        params["temperature_unit"] = "fahrenheit"
        params["wind_speed_unit"] = "mph"
        params["precipitation_unit"] = "inch"
    return params


def summarize_open_meteo(data: dict[str, Any], units: str) -> str:
    daily = data.get("daily") or {}
    high = _first(daily.get("temperature_2m_max"))
    low = _first(daily.get("temperature_2m_min"))
    precip = _first(daily.get("precipitation_probability_max"))
    weather_code = _first(daily.get("weather_code"))

    if high is None and low is None and weather_code is None:
        raise ValueError("Open-Meteo response did not include daily weather data")

    temp_unit = "F" if units == "imperial" else "C"
    parts: list[str] = []
    if high is not None:
        parts.append(f"high {round(float(high))} deg {temp_unit}")
    if low is not None:
        parts.append(f"low {round(float(low))} deg {temp_unit}")

    condition = WEATHER_CODES.get(int(weather_code), "weather code " + str(weather_code)) if weather_code is not None else "conditions unavailable"
    sentence = condition.capitalize()
    if parts:
        sentence += ", " + ", ".join(parts)
    if precip is not None:
        sentence += f", precipitation chance {round(float(precip))}%"
    return sentence + "."


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None
