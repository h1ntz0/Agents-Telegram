"""Weather lookup tool using the free Open-Meteo Geocoding and Forecast APIs."""

import re
import urllib.parse
from typing import Any, Dict, Optional, Tuple
import httpx
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult

WMO_WEATHER_CODES: Dict[int, Tuple[str, str]] = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    56: ("Light freezing drizzle", "🌨️"),
    57: ("Dense freezing drizzle", "🌨️"),
    61: ("Slight rain", "🌦️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "🌨️"),
    67: ("Heavy freezing rain", "🌨️"),
    71: ("Slight snow fall", "🌨️"),
    73: ("Moderate snow fall", "❄️"),
    75: ("Heavy snow fall", "❄️"),
    77: ("Snow grains", "❄️"),
    80: ("Slight rain showers", "🌦️"),
    81: ("Moderate rain showers", "🌧️"),
    82: ("Violent rain showers", "⛈️"),
    85: ("Slight snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm with slight hail", "⛈️"),
    99: ("Thunderstorm with heavy hail", "⛈️"),
}


def interpret_weather_code(code: int) -> Tuple[str, str]:
    """Return human description and emoji for WMO code."""
    return WMO_WEATHER_CODES.get(code, ("Unknown", "🌡️"))


class WeatherTool(BaseTool):
    """Free Open-Meteo weather forecast tool by city name or geographic coordinates."""

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_weather",
            description="Get current weather and multi-day forecast for any city or latitude/longitude coordinates using Open-Meteo.",
            parameters={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name (e.g. 'Jakarta', 'Tokyo', 'London') or query 'weather in Tokyo'."
                    },
                    "location": {
                        "type": "string",
                        "description": "City name or coordinates 'latitude,longitude' (e.g. '-6.2088,106.8456')."
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of forecast days (1 to 7, default: 3)."
                    }
                },
            },
            permission=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            requires_confirmation=False
        )

    def parse_city_query(self, query: str) -> str:
        """Strip conversational prefixes like 'weather in', 'forecast for'."""
        cleaned = query.strip()
        cleaned = re.sub(r"^(?:weather|forecast)\s+(?:in|for)\s+", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned

    async def _resolve_coordinates(self, location: str, client: httpx.AsyncClient) -> Tuple[float, float, str, str]:
        """Parse lat/lon or query Open-Meteo Geocoding API."""
        clean_name = self.parse_city_query(location)

        # 1. Direct coordinates
        coord_match = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)$", clean_name)
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            return lat, lon, f"{lat:.4f}, {lon:.4f}", "UTC"

        # 2. Geocoding search
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(clean_name)}&count=1&language=en&format=json"
        res = await client.get(geo_url)
        if res.status_code != 200:
            raise RuntimeError(f"Geocoding API failed with HTTP {res.status_code}")

        data = res.json()
        results = data.get("results", [])
        if not results:
            raise ValueError(f"Could not find coordinates for location '{clean_name}'.")

        top = results[0]
        name = top.get("name", clean_name)
        admin = top.get("admin1", "")
        country = top.get("country", "")
        parts = [name, country] if not admin or admin == name else [name, admin, country]
        full_name = ", ".join(p for p in parts if p)
        tz = top.get("timezone", "auto")
        return float(top["latitude"]), float(top["longitude"]), full_name, tz

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        raw_location = str(arguments.get("city") or arguments.get("location") or "").strip()
        if not raw_location:
            return ToolResult(content="City or location parameter is required.", is_error=True)

        days = int(arguments.get("days", 3))
        days = max(1, min(days, 7))

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                lat, lon, place_name, timezone_str = await self._resolve_coordinates(raw_location, client)

                forecast_url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={lat}&longitude={lon}&"
                    f"current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m&"
                    f"daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&"
                    f"forecast_days={days}&"
                    f"timezone=auto"
                )

                res = await client.get(forecast_url)
                if res.status_code != 200:
                    return ToolResult(content=f"Open-Meteo weather API returned HTTP {res.status_code}.", is_error=True)

                data = res.json()
                current = data.get("current", {})
                daily = data.get("daily", {})

                # Parse current conditions
                cur_code = int(current.get("weather_code", 0))
                desc, emoji = interpret_weather_code(cur_code)
                cur_temp = current.get("temperature_2m", "N/A")
                cur_feel = current.get("apparent_temperature", "N/A")
                cur_hum = current.get("relative_humidity_2m", "N/A")
                cur_wind = current.get("wind_speed_10m", "N/A")
                cur_precip = current.get("precipitation", 0.0)

                lines = [
                    f"📍 Weather for {place_name}",
                    f"Current Condition: {emoji} {desc}",
                    f"• Temperature: {cur_temp}°C (Feels like: {cur_feel}°C)",
                    f"• Humidity: {cur_hum}% | Wind: {cur_wind} km/h | Precip: {cur_precip} mm",
                ]

                # Daily forecast
                dates = daily.get("time", [])
                if dates:
                    lines.append("")
                    lines.append(f"📅 {len(dates)}-Day Forecast:")
                    codes = daily.get("weather_code", [])
                    max_temps = daily.get("temperature_2m_max", [])
                    min_temps = daily.get("temperature_2m_min", [])
                    precip_probs = daily.get("precipitation_probability_max", [])

                    for i in range(len(dates)):
                        d_date = dates[i]
                        d_code = int(codes[i]) if i < len(codes) else 0
                        d_desc, d_emoji = interpret_weather_code(d_code)
                        d_max = max_temps[i] if i < len(max_temps) else "?"
                        d_min = min_temps[i] if i < len(min_temps) else "?"
                        d_prob = f" (Rain: {precip_probs[i]}%)" if i < len(precip_probs) and precip_probs[i] is not None else ""
                        lines.append(f"• {d_date}: {d_emoji} {d_min}°C – {d_max}°C — {d_desc}{d_prob}")

                return ToolResult(
                    content="\n".join(lines),
                    metadata={
                        "location": place_name,
                        "latitude": lat,
                        "longitude": lon,
                        "current_temp": cur_temp,
                        "weather_code": cur_code
                    }
                )

        except Exception as e:
            return ToolResult(content=f"Weather lookup error: {str(e)}", is_error=True)
