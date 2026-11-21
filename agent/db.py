"""Read-only database access for the Employee Weather workflow.

Only predefined SELECT statements are exposed.
No arbitrary SQL execution is available to agents.
"""

import os
from functools import lru_cache
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    Format,
    StatementParameterListItem,
    StatementState,
)


WAREHOUSE_ID = os.getenv(
    "DATABRICKS_WAREHOUSE_ID",
    "bfe34b9264ad57b8",
)

CATALOG = "workspace"
SCHEMA = "rlus_demo"

EMPLOYEES_TABLE = f"{CATALOG}.{SCHEMA}.employees"
LOCATIONS_TABLE = f"{CATALOG}.{SCHEMA}.locations"


@lru_cache(maxsize=1)
def get_workspace_client() -> WorkspaceClient:
    """Create and reuse the configured Databricks workspace client."""
    profile = os.getenv("DATABRICKS_CONFIG_PROFILE", "rlus-new")
    return WorkspaceClient(profile=profile)


def _execute_select(
    statement: str,
    parameters: list[StatementParameterListItem] | None = None,
) -> list[dict[str, Any]]:
    """Execute an internal, predefined SELECT and return dictionary rows.

    This private helper must only be called with SQL constants defined
    in this module. Do not pass user or LLM-generated SQL here.
    """
    client = get_workspace_client()

    response = client.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=statement,
        parameters=parameters,
        wait_timeout="30s",
        format=Format.JSON_ARRAY,
        row_limit=1000,
    )

    status = response.status

    if status is None or status.state != StatementState.SUCCEEDED:
        error = status.error if status else "No statement status returned"
        raise RuntimeError(f"Databricks SQL query failed: {error}")

    if response.manifest is None or response.manifest.schema is None:
        raise RuntimeError("Databricks SQL returned no result schema.")

    columns = [
        column.name
        for column in response.manifest.schema.columns
    ]

    if response.result is None:
        return []

    data = response.result.data_array or []

    return [
        dict(zip(columns, row))
        for row in data
    ]


def fetch_employees(
    employee_name: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch permitted employee fields, optionally filtering by exact name."""
    statement = f"""
        SELECT
            employee_id,
            employee_name,
            location_id
        FROM {EMPLOYEES_TABLE}
    """

    parameters = None
    if employee_name is not None:
        employee_name = employee_name.strip()
        if not employee_name:
            raise ValueError("Employee name cannot be empty.")

        statement += """
            WHERE LOWER(employee_name) = LOWER(:employee_name)
        """
        parameters = [
            StatementParameterListItem(
                name="employee_name",
                type="STRING",
                value=employee_name,
            )
        ]

    statement += " ORDER BY employee_id"
    rows = _execute_select(statement, parameters)

    return [
        {
            "employee_id": int(row["employee_id"]),
            "employee_name": row["employee_name"],
            "location_id": int(row["location_id"]),
        }
        for row in rows
    ]


def fetch_locations() -> list[dict[str, Any]]:
    """Fetch location IDs and their city, state, and country."""
    statement = f"""
        SELECT
            location_id,
            city,
            state,
            country
        FROM {LOCATIONS_TABLE}
        ORDER BY location_id
    """

    rows = _execute_select(statement)

    return [
        {
            "location_id": int(row["location_id"]),
            "city": row["city"],
            "state": row["state"],
            "country": row["country"],
        }
        for row in rows
    ]
