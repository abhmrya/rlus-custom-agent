"""Streamable HTTP MCP server for the RLUS Employee Weather workflow."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agent.tools.weather_service import (
    current_weather as fetch_current_weather,
    weather_for_cities as fetch_weather_for_cities,
    weather_forecast as fetch_weather_forecast,
    historical_weather as fetch_historical_weather,
)


mcp = FastMCP(
    name="RLUS Employee Weather MCP",
    instructions=(
        "Provides current, batch, forecast, and historical weather "
        "using Open-Meteo. Use batch weather for multiple employee "
        "locations to minimize forecast API requests."
    ),
    host="127.0.0.1",
    port=8001,
    streamable_http_path="/mcp",
    stateless_http=True,
)


@mcp.tool()
async def current_weather(city: str) -> dict[str, Any]:
    """Get current weather conditions for one Indian city.

    Args:
        city: City name, for example Delhi or Bangalore.
    """
    return await fetch_current_weather(city)


@mcp.tool()
async def weather_for_cities(cities: list[str]) -> dict[str, Any]:
    """Get current weather for multiple Indian cities in one batch.

    Args:
        cities: City names, for example Delhi, Noida, Mumbai, Pune.
    """
    return await fetch_weather_for_cities(cities)


@mcp.tool()
async def weather_forecast(
    city: str,
    days: int = 7,
) -> dict[str, Any]:
    """Get daily weather forecast for a city for 1 to 14 days.

    Args:
        city: Indian city name.
        days: Number of forecast days, from 1 to 14.
    """
    return await fetch_weather_forecast(city, days)


@mcp.tool()
async def historical_weather(
    city: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Get historical daily weather for a city.

    Args:
        city: Indian city name.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
    """
    return await fetch_historical_weather(city, start_date, end_date)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
