"""Open-Meteo weather service used by the Employee Weather MCP."""

import asyncio
from datetime import date, timedelta
from typing import Any

import httpx


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

REQUEST_TIMEOUT = 30.0
MAX_CITIES = 50

CITY_ALIASES = {
    "bangalore": "Bengaluru",
}


def _normalise_city(city: str) -> str:
    """Resolve common city-name aliases for geocoding."""
    cleaned = city.strip()
    return CITY_ALIASES.get(cleaned.casefold(), cleaned)


async def _resolve_city(
    client: httpx.AsyncClient,
    city: str,
    country_code: str = "IN",
) -> dict[str, Any]:
    """Resolve a city into geographic coordinates."""

    if not city or not city.strip():
        raise ValueError("City cannot be empty.")

    search_name = _normalise_city(city)

    response = await client.get(
        GEOCODING_URL,
        params={
            "name": search_name,
            "count": 10,
            "language": "en",
            "format": "json",
            "countryCode": country_code,
        },
    )
    response.raise_for_status()

    results = response.json().get("results") or []

    if not results:
        raise ValueError(f"Location not found: {city}")

    exact_match = next(
        (
            item for item in results
            if item.get("name", "").casefold() == search_name.casefold()
        ),
        results[0],
    )

    return {
        "requested_city": city.strip(),
        "resolved_city": exact_match["name"],
        "country": exact_match.get("country", ""),
        "latitude": exact_match["latitude"],
        "longitude": exact_match["longitude"],
        "timezone": exact_match.get("timezone", "auto"),
    }


async def _get_current_weather(
    client: httpx.AsyncClient,
    location: dict[str, Any],
) -> dict[str, Any]:
    """Fetch current weather for one resolved location."""

    response = await client.get(
        FORECAST_URL,
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": (
                "temperature_2m,"
                "apparent_temperature,"
                "relative_humidity_2m,"
                "precipitation,"
                "weather_code,"
                "wind_speed_10m"
            ),
            "timezone": "auto",
        },
    )
    response.raise_for_status()

    current = response.json().get("current")

    if not current:
        raise RuntimeError("Weather API returned no current conditions.")

    return {
        "city": location["requested_city"],
        "resolved_city": location["resolved_city"],
        "country": location["country"],
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "humidity_percent": current.get("relative_humidity_2m"),
        "precipitation_mm": current.get("precipitation"),
        "weather_code": current.get("weather_code"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "observed_at": current.get("time"),
        "timezone": response.json().get("timezone"),
        "data_source": "Open-Meteo",
    }


async def current_weather(city: str) -> dict[str, Any]:
    """Get current weather for a single city."""

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        location = await _resolve_city(client, city)
        return await _get_current_weather(client, location)


async def weather_for_cities(
    cities: list[str],
) -> dict[str, Any]:
    """Get current weather for multiple cities using one batch forecast request."""

    unique_cities = list(dict.fromkeys(
        city.strip() for city in cities if city and city.strip()
    ))

    if not unique_cities:
        raise ValueError("At least one valid city is required.")

    if len(unique_cities) > MAX_CITIES:
        raise ValueError(f"Maximum supported cities: {MAX_CITIES}")

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        geocoding_results = await asyncio.gather(
            *[
                _resolve_city(client, city)
                for city in unique_cities
            ],
            return_exceptions=True,
        )

        locations = []
        errors = []

        for city, result in zip(unique_cities, geocoding_results):
            if isinstance(result, Exception):
                errors.append({
                    "city": city,
                    "error": str(result),
                })
            else:
                locations.append(result)

        if not locations:
            return {
                "requested_count": len(unique_cities),
                "resolved_count": 0,
                "weather": [],
                "errors": errors,
                "data_source": "Open-Meteo",
            }

        response = await client.get(
            FORECAST_URL,
            params={
                "latitude": ",".join(
                    str(item["latitude"]) for item in locations
                ),
                "longitude": ",".join(
                    str(item["longitude"]) for item in locations
                ),
                "current": (
                    "temperature_2m,"
                    "apparent_temperature,"
                    "relative_humidity_2m,"
                    "precipitation,"
                    "weather_code,"
                    "wind_speed_10m"
                ),
                "timezone": "auto",
            },
        )
        response.raise_for_status()

        payload = response.json()

        # Open-Meteo returns a list for multiple coordinate pairs.
        # A single coordinate pair may return one dictionary.
        weather_payloads = (
            payload if isinstance(payload, list) else [payload]
        )

        weather = []

        for location, item in zip(locations, weather_payloads):
            current = item.get("current") or {}

            if not current:
                errors.append({
                    "city": location["requested_city"],
                    "error": "No current weather returned.",
                })
                continue

            weather.append({
                "city": location["requested_city"],
                "resolved_city": location["resolved_city"],
                "country": location["country"],
                "temperature_c": current.get("temperature_2m"),
                "feels_like_c": current.get("apparent_temperature"),
                "humidity_percent": current.get("relative_humidity_2m"),
                "precipitation_mm": current.get("precipitation"),
                "weather_code": current.get("weather_code"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "observed_at": current.get("time"),
                "timezone": item.get("timezone"),
            })

        return {
            "requested_count": len(unique_cities),
            "resolved_count": len(weather),
            "weather": weather,
            "errors": errors,
            "forecast_api_requests": 1,
            "data_source": "Open-Meteo",
        }


async def weather_forecast(
    city: str,
    days: int = 7,
) -> dict[str, Any]:
    """Get daily weather forecast for the next 1 to 14 days."""

    if not 1 <= days <= 14:
        raise ValueError("Forecast days must be between 1 and 14.")

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        location = await _resolve_city(client, city)

        response = await client.get(
            FORECAST_URL,
            params={
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "daily": (
                    "weather_code,"
                    "temperature_2m_max,"
                    "temperature_2m_min,"
                    "precipitation_sum,"
                    "wind_speed_10m_max"
                ),
                "forecast_days": days,
                "timezone": "auto",
            },
        )
        response.raise_for_status()

        payload = response.json()

        return {
            "city": location["requested_city"],
            "resolved_city": location["resolved_city"],
            "country": location["country"],
            "timezone": payload.get("timezone"),
            "daily": payload.get("daily", {}),
            "data_source": "Open-Meteo",
        }


def _validate_historical_dates(
    start_date: str,
    end_date: str,
) -> tuple[date, date]:
    """Validate a historical date range of at most 366 inclusive days."""

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("Dates must use YYYY-MM-DD format.") from exc

    if start > end:
        raise ValueError("start_date must not be after end_date.")

    if end >= date.today():
        raise ValueError("Historical end_date must be before today.")

    if (end - start).days > 365:
        raise ValueError("Historical date range cannot exceed 366 days.")

    return start, end


async def historical_weather(
    city: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Get historical daily weather for a date range of at most 366 days."""

    start, end = _validate_historical_dates(start_date, end_date)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        location = await _resolve_city(client, city)

        response = await client.get(
            ARCHIVE_URL,
            params={
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": (
                    "weather_code,"
                    "temperature_2m_max,"
                    "temperature_2m_min,"
                    "precipitation_sum,"
                    "wind_speed_10m_max"
                ),
                "timezone": "auto",
            },
        )
        response.raise_for_status()

        payload = response.json()

        return {
            "city": location["requested_city"],
            "resolved_city": location["resolved_city"],
            "country": location["country"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": payload.get("timezone"),
            "daily": payload.get("daily", {}),
            "data_source": "Open-Meteo Archive",
        }
