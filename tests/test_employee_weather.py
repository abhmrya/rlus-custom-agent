import pytest

from agent import db
from agent import orchestrator


def test_fetch_employees_uses_parameterized_exact_name_filter(monkeypatch):
    captured = {}

    def fake_execute(statement, parameters=None):
        captured["statement"] = statement
        captured["parameters"] = parameters
        return [{
            "employee_id": 101,
            "employee_name": "Rahul Sharma",
            "location_id": 1,
        }]

    monkeypatch.setattr(db, "_execute_select", fake_execute)

    result = db.fetch_employees("Rahul Sharma")

    assert len(result) == 1
    assert result[0]["employee_name"] == "Rahul Sharma"
    assert "LOWER(employee_name) = LOWER(:employee_name)" in captured["statement"]
    assert len(captured["parameters"]) == 1
    assert captured["parameters"][0].name == "employee_name"
    assert captured["parameters"][0].value == "Rahul Sharma"


def test_fetch_employees_rejects_blank_name(monkeypatch):
    def unexpected_execute(*args, **kwargs):
        pytest.fail("SQL must not execute for a blank employee name")

    monkeypatch.setattr(db, "_execute_select", unexpected_execute)

    with pytest.raises(ValueError, match="Employee name cannot be empty"):
        db.fetch_employees("   ")


@pytest.fixture
def employee_weather_workflow(monkeypatch):
    employees = [
        {"employee_id": 101, "employee_name": "Rahul Sharma", "location_id": 1},
        {"employee_id": 102, "employee_name": "Priya Verma", "location_id": 1},
        {"employee_id": 103, "employee_name": "Amit Kumar", "location_id": 2},
    ]

    locations = [
        {"location_id": 1, "city": "Delhi", "state": "Delhi", "country": "India"},
        {"location_id": 2, "city": "Noida", "state": "Uttar Pradesh", "country": "India"},
    ]

    class FakeEmployeeAgent:
        def run(self, employee_name=None):
            if employee_name is None:
                return employees
            return [
                employee for employee in employees
                if employee["employee_name"].casefold()
                == employee_name.casefold()
            ]

    class FakeLocationAgent:
        def run(self):
            return locations

    weather_calls = []

    async def fake_weather(cities):
        weather_calls.append(cities)
        return {
            "weather": [
                {
                    "city": city,
                    "country": "India",
                    "temperature_c": 25,
                    "feels_like_c": 26,
                    "humidity_percent": 60,
                    "precipitation_mm": 0,
                    "weather_code": 1,
                    "wind_speed_kmh": 10,
                    "observed_at": "2026-11-19T12:00",
                }
                for city in cities
            ],
            "errors": [],
            "requested_count": len(cities),
            "resolved_count": len(cities),
            "forecast_api_requests": len(cities),
        }

    monkeypatch.setattr(
        orchestrator,
        "build_sub_agents",
        lambda: (FakeEmployeeAgent(), FakeLocationAgent()),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_weather_for_cities",
        fake_weather,
    )

    return orchestrator.EmployeeWeatherOrchestrator(), weather_calls


@pytest.mark.asyncio
async def test_single_employee_fetches_only_their_office_weather(
    employee_weather_workflow,
):
    workflow, weather_calls = employee_weather_workflow

    result = await workflow.run_with_weather("Rahul Sharma")

    assert result["employee_count"] == 1
    assert result["employees"][0]["employee_name"] == "Rahul Sharma"
    assert weather_calls == [["Delhi"]]


@pytest.mark.asyncio
async def test_missing_name_returns_all_employees_and_unique_cities(
    employee_weather_workflow,
):
    workflow, weather_calls = employee_weather_workflow

    result = await workflow.run_with_weather()

    assert result["employee_count"] == 3
    assert {item["employee_name"] for item in result["employees"]} == {
        "Rahul Sharma",
        "Priya Verma",
        "Amit Kumar",
    }
    assert weather_calls == [["Delhi", "Noida"]]


@pytest.mark.asyncio
async def test_unknown_employee_does_not_call_weather(
    employee_weather_workflow,
):
    workflow, weather_calls = employee_weather_workflow

    result = await workflow.run_with_weather("Unknown Person")

    assert result["employee_count"] == 0
    assert "No employee found" in result["message"]
    assert weather_calls == []


@pytest.mark.asyncio
async def test_employee_with_missing_location_mapping_returns_clear_message(
    monkeypatch,
):
    class FakeEmployeeAgent:
        def run(self, employee_name=None):
            return [{
                "employee_id": 111,
                "employee_name": "Test Employee",
                "location_id": 999,
            }]

    class FakeLocationAgent:
        def run(self):
            return []

    async def unexpected_weather_call(cities):
        pytest.fail("Weather must not be called without valid locations")

    monkeypatch.setattr(
        orchestrator,
        "build_sub_agents",
        lambda: (FakeEmployeeAgent(), FakeLocationAgent()),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_weather_for_cities",
        unexpected_weather_call,
    )

    workflow = orchestrator.EmployeeWeatherOrchestrator()
    result = await workflow.run_with_weather("Test Employee")

    assert result["source_employee_count"] == 1
    assert result["employee_count"] == 0
    assert result["unmatched_location_employee_count"] == 1
    assert result["missing_location_ids"] == [999]
    assert result["message"] == (
        "Employee records were found, but none have valid location mappings."
    )
