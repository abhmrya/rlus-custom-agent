import httpx
import pytest

from agent.tools import weather_service as service


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, params=None):
        self.requests.append((url, params))
        return next(self.responses)


@pytest.mark.asyncio
async def test_current_weather(monkeypatch):
    client = FakeAsyncClient([
        FakeResponse({
            "results": [{
                "name": "Delhi",
                "country": "India",
                "latitude": 28.61,
                "longitude": 77.20,
                "timezone": "Asia/Kolkata",
            }]
        }),
        FakeResponse({
            "timezone": "Asia/Kolkata",
            "current": {
                "temperature_2m": 28,
                "apparent_temperature": 30,
                "relative_humidity_2m": 55,
                "precipitation": 0,
                "weather_code": 1,
                "wind_speed_10m": 12,
                "time": "2026-11-19T12:00",
            }
        }),
    ])

    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: client,
    )

    result = await service.current_weather("Delhi")

    assert result["city"] == "Delhi"
    assert result["temperature_c"] == 28
    assert result["feels_like_c"] == 30
    assert result["data_source"] == "Open-Meteo"
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_batch_weather_uses_one_forecast_request(monkeypatch):
    client = FakeAsyncClient([
        FakeResponse({
            "results": [{
                "name": "Delhi",
                "country": "India",
                "latitude": 28.61,
                "longitude": 77.20,
                "timezone": "Asia/Kolkata",
            }]
        }),
        FakeResponse({
            "results": [{
                "name": "Noida",
                "country": "India",
                "latitude": 28.53,
                "longitude": 77.39,
                "timezone": "Asia/Kolkata",
            }]
        }),
        FakeResponse([
            {
                "timezone": "Asia/Kolkata",
                "current": {"temperature_2m": 28, "time": "2026-11-19T12:00"},
            },
            {
                "timezone": "Asia/Kolkata",
                "current": {"temperature_2m": 27, "time": "2026-11-19T12:00"},
            },
        ]),
    ])

    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: client,
    )

    result = await service.weather_for_cities(["Delhi", "Noida", "Delhi"])

    assert result["requested_count"] == 2
    assert result["resolved_count"] == 2
    assert len(result["weather"]) == 2
    assert result["forecast_api_requests"] == 1
    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_batch_weather_rejects_empty_cities():
    with pytest.raises(ValueError, match="At least one valid city"):
        await service.weather_for_cities(["", "  "])


@pytest.mark.asyncio
async def test_batch_weather_rejects_too_many_cities():
    cities = [f"City {index}" for index in range(service.MAX_CITIES + 1)]

    with pytest.raises(ValueError, match="Maximum supported cities"):
        await service.weather_for_cities(cities)


@pytest.mark.parametrize(
    "start_date,end_date",
    [
        ("invalid", "2026-11-01"),
        ("2026-11-10", "2026-11-01"),
        ("2026-11-01", "2026-11-19"),
        ("2025-10-01", "2026-11-01"),
    ],
)
def test_historical_date_validation(start_date, end_date):
    with pytest.raises(ValueError):
        service._validate_historical_dates(start_date, end_date)


def test_bangalore_alias_normalization():
    assert service._normalise_city("Bangalore") == "Bengaluru"
    assert service._normalise_city("Delhi") == "Delhi"
