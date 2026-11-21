"""Specialized read-only agents for Employee Weather."""

from typing import Any

from agent.db import fetch_employees, fetch_locations


class EmployeeAgent:
    """Agent responsible for retrieving permitted employee information."""

    name = "employee_agent"

    def run(
        self,
        employee_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all employees or filter by an exact employee name."""
        return fetch_employees(employee_name=employee_name)


class LocationAgent:
    """Agent responsible for retrieving office location information."""

    name = "location_agent"

    def run(self) -> list[dict[str, Any]]:
        """Return location IDs and geographic information."""
        return fetch_locations()


def build_sub_agents() -> tuple[EmployeeAgent, LocationAgent]:
    """Create both specialized agents."""
    return EmployeeAgent(), LocationAgent()
