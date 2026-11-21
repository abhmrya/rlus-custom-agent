"""Employee-wise office weather tool backed by the local Weather MCP server."""

import json

from langchain_core.tools import tool

from agent.orchestrator import run_employee_weather_with_weather


@tool
async def get_employee_weather(employee_name: str | None = None) -> str:
    """Get current office weather for all employees or one named employee.

    If employee_name is provided, retrieve only the employee whose name
    matches exactly (case-insensitive). If omitted, retrieve all employees.

    Reads only permitted employee and location fields from workspace.rlus_demo,
    joins records by location_id, and retrieves weather for each unique city
    through the local Employee Weather MCP server.
    """
    result = await run_employee_weather_with_weather(
        employee_name=employee_name
    )
    return json.dumps(result, ensure_ascii=False, default=str)
