"""Orchestrator for the Employee Weather workflow."""

from typing import Any

from agent.sub_agents import build_sub_agents
from agent.mcp_client import fetch_weather_for_cities


class EmployeeWeatherOrchestrator:
    """Coordinates employee, location, and weather services."""

    def __init__(self) -> None:
        self.employee_agent, self.location_agent = build_sub_agents()

    def run(
        self,
        employee_name: str | None = None,
    ) -> dict[str, Any]:
        """Fetch all employees or one exact employee, then join locations."""

        employees = self.employee_agent.run(employee_name=employee_name)
        locations = self.location_agent.run()

        location_lookup = {
            location["location_id"]: location
            for location in locations
        }

        employee_locations = []
        missing_location_ids = []

        for employee in employees:
            location = location_lookup.get(employee["location_id"])

            if location is None:
                missing_location_ids.append(employee["location_id"])
                continue

            employee_locations.append({
                **employee,
                "city": location["city"],
                "state": location["state"],
                "country": location["country"],
            })

        unique_cities = list(dict.fromkeys(
            (
                item["city"],
                item["country"],
            )
            for item in employee_locations
        ))

        weather_locations = [
            {"city": city, "country": country}
            for city, country in unique_cities
        ]

        return {
            "employees": employee_locations,
            "weather_locations": weather_locations,
            "employee_count": len(employee_locations),
            "source_employee_count": len(employees),
            "unmatched_location_employee_count": len(missing_location_ids),
            "unique_city_count": len(weather_locations),
            "missing_location_ids": sorted(set(missing_location_ids)),
        }

    async def run_with_weather(
        self,
        employee_name: str | None = None,
    ) -> dict[str, Any]:
        """Fetch filtered employee data, then attach MCP weather."""

        workflow = self.run(employee_name=employee_name)

        if not workflow["employees"]:
            workflow.update({
                "weather_requested_count": 0,
                "weather_resolved_count": 0,
                "weather_errors": [],
                "forecast_api_requests": 0,
                "data_source": None,
                "message": (
                    f"No employee found with exact name '{employee_name}'."
                    if not workflow["source_employee_count"] and employee_name
                    else "No employee records found."
                    if not workflow["source_employee_count"]
                    else "Employee records were found, but none have valid location mappings."
                ),
            })
            return workflow

        cities = [
            location["city"]
            for location in workflow["weather_locations"]
        ]

        # One MCP batch call for all unique employee cities.
        weather_result = await fetch_weather_for_cities(cities)

        weather_lookup = {
            (
                item["city"].strip().casefold(),
                item["country"].strip().casefold(),
            ): item
            for item in weather_result.get("weather", [])
        }

        error_lookup = {
            item["city"].strip().casefold(): item["error"]
            for item in weather_result.get("errors", [])
        }

        employee_weather = []

        for employee in workflow["employees"]:
            key = (
                employee["city"].strip().casefold(),
                employee["country"].strip().casefold(),
            )

            weather = weather_lookup.get(key)

            if weather:
                employee_weather.append({
                    **employee,
                    "weather_status": "available",
                    "temperature_c": weather.get("temperature_c"),
                    "feels_like_c": weather.get("feels_like_c"),
                    "humidity_percent": weather.get("humidity_percent"),
                    "precipitation_mm": weather.get("precipitation_mm"),
                    "weather_code": weather.get("weather_code"),
                    "wind_speed_kmh": weather.get("wind_speed_kmh"),
                    "observed_at": weather.get("observed_at"),
                    "weather_source": "Open-Meteo",
                })
            else:
                employee_weather.append({
                    **employee,
                    "weather_status": "unavailable",
                    "weather_error": error_lookup.get(
                        employee["city"].casefold(),
                        "Weather data unavailable for this location.",
                    ),
                })

        workflow.update({
            "employees": employee_weather,
            "weather_requested_count": weather_result.get(
                "requested_count", 0
            ),
            "weather_resolved_count": weather_result.get(
                "resolved_count", 0
            ),
            "weather_errors": weather_result.get("errors", []),
            "forecast_api_requests": weather_result.get(
                "forecast_api_requests", 0
            ),
            "data_source": "Open-Meteo",
        })

        return workflow


def run_employee_weather_workflow(
    employee_name: str | None = None,
) -> dict[str, Any]:
    """Synchronous employee-location workflow entry point."""
    return EmployeeWeatherOrchestrator().run(employee_name=employee_name)


async def run_employee_weather_with_weather(
    employee_name: str | None = None,
) -> dict[str, Any]:
    """Complete asynchronous employee-location-weather workflow."""
    return await EmployeeWeatherOrchestrator().run_with_weather(
        employee_name=employee_name
    )


if __name__ == "__main__":
    import asyncio
    import json

    result = asyncio.run(run_employee_weather_with_weather())
    print(json.dumps(result, indent=2, ensure_ascii=False))
