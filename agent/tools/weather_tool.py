
"""Weather lookup tool using Open-Meteo APIs."""

import httpx
from langchain_core.tools import tool


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@tool
def get_location_weather(location: str) -> str:
    """Get current weather for a city, town, or location.

    Args:
        location: Name of the city or place, for example Noida or Kushinagar.
    """
    location = location.strip()

    if not location:
        return "Please provide a location name."

    try:
        # Step 1: Convert the location name into coordinates.
        geo_response = httpx.get(
            GEOCODING_URL,
            params={
                "name": location,
                "count": 5,
                "language": "en",
                "format": "json",
            },
            timeout=15.0,
        )
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        results = geo_data.get("results", [])

        if not results:
            return f"I could not find the location: {location}"

        # Use the best matching result for now.
        place = results[0]
        latitude = place["latitude"]
        longitude = place["longitude"]

        # Step 2: Fetch current weather.
        weather_response = httpx.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,"
                    "relative_humidity_2m,"
                    "apparent_temperature,"
                    "is_day,"
                    "precipitation,"
                    "weather_code,"
                    "wind_speed_10m"
                ),
                "timezone": "auto",
            },
            timeout=15.0,
        )
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        current = weather_data.get("current")

        if not current:
            return "Weather information is currently unavailable."

        return (
            f"Current weather for {place['name']}, "
            f"{place.get('admin1', '')}, {place.get('country', '')}\n"
            f"Temperature: {current.get('temperature_2m')} °C\n"
            f"Feels like: {current.get('apparent_temperature')} °C\n"
            f"Humidity: {current.get('relative_humidity_2m')}%\n"
            f"Wind speed: {current.get('wind_speed_10m')} km/h\n"
            f"Precipitation: {current.get('precipitation')} mm\n"
            f"Weather code: {current.get('weather_code')}\n"
            f"Timezone: {weather_data.get('timezone')}\n"
            f"Data source: Open-Meteo"
        )

    except httpx.TimeoutException:
        return "Weather service timed out. Please try again."

    except httpx.HTTPStatusError as exc:
        return (
            "Weather service returned an error: "
            f"HTTP {exc.response.status_code}"
        )

    except (httpx.RequestError, KeyError, ValueError) as exc:
        return f"Unable to fetch weather information: {exc}"
