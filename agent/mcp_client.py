"""Client for the local Employee Weather Streamable HTTP MCP server."""

import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from databricks.sdk import WorkspaceClient


WEATHER_MCP_URL = os.getenv(
    "WEATHER_MCP_URL",
    "http://127.0.0.1:8001/mcp",
)


async def fetch_weather_for_cities(
    cities: list[str],
) -> dict[str, Any]:
    """Fetch batch weather through the Weather MCP server."""

    if not cities:
        raise ValueError("At least one city is required.")

    headers = None
    if not WEATHER_MCP_URL.startswith(("http://127.0.0.1", "http://localhost")):
        headers = WorkspaceClient().config.authenticate()

    async with streamablehttp_client(
        WEATHER_MCP_URL,
        headers=headers,
    ) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "weather_for_cities",
                {"cities": cities},
            )

            if result.isError:
                raise RuntimeError("Weather MCP tool execution failed.")

            # MCP servers may return structured content or text content.
            if result.structuredContent:
                return result.structuredContent

            for content in result.content:
                if hasattr(content, "text"):
                    try:
                        return json.loads(content.text)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            "Weather MCP returned invalid JSON."
                        ) from exc

            raise RuntimeError(
                "Weather MCP returned no readable result."
            )
