import datetime
import sqlite3

import pytest
import requests

from src.api_client import WeatherAPIClient
from src.config import FORECAST_DAYS, PAST_DAYS


@pytest.fixture
def client(tmp_path) -> WeatherAPIClient:
    return WeatherAPIClient(db_path=str(tmp_path / "cache.db"))


def test_cache_roundtrip(client):
    client._set_cached_data("key", {"a": 1})
    assert client._get_cached_data("key") == {"a": 1}


def test_cache_expired_entry_is_ignored(client):
    client._set_cached_data("key", {"a": 1})
    old = (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat()
    with sqlite3.connect(client.db_path) as conn:
        conn.execute("UPDATE api_cache SET timestamp = ? WHERE key = ?", (old, "key"))
    assert client._get_cached_data("key") is None


def test_mock_mode_returns_expected_structure(client):
    data = client.fetch_weather_and_air_quality(48.85, 2.35, mock_mode=True)
    assert len(data["weather"]["hourly"]["time"]) == 24 * (PAST_DAYS + FORECAST_DAYS)
    assert "pm2_5" in data["air_quality"]["hourly"]


def test_network_error_falls_back_to_mock(client, monkeypatch):
    def fail(*args, **kwargs):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(client.session, "get", fail)
    data = client.fetch_weather_and_air_quality(48.85, 2.35)
    assert "hourly" in data["weather"]
    assert data["source"] == "mock"


def test_cached_response_avoids_api_call(client, monkeypatch):
    client._set_cached_data("data_v2_48.85_2.35", {"weather": {}, "air_quality": {}, "cached": True})

    def fail(*args, **kwargs):
        raise AssertionError("API should not be called")

    monkeypatch.setattr(client.session, "get", fail)
    data = client.fetch_weather_and_air_quality(48.85, 2.35)
    assert data["cached"] is True
    assert data["source"] == "cache"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_mock_data_contains_all_required_variables(client):
    from src.config import AIR_QUALITY_VARIABLES, WEATHER_VARIABLES
    data = client.fetch_weather_and_air_quality(48.85, 2.35, mock_mode=True)
    assert set(WEATHER_VARIABLES) <= set(data["weather"]["hourly"])
    assert set(AIR_QUALITY_VARIABLES) <= set(data["air_quality"]["hourly"])


def test_geocode_city(client, monkeypatch):
    payload = {"results": [{"name": "Bordeaux", "country": "France", "latitude": 44.84, "longitude": -0.58}]}
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse(payload))
    assert client.geocode_city("Bordeaux") == {"name": "Bordeaux", "country": "France", "lat": 44.84, "lon": -0.58}


def test_geocode_unknown_city(client, monkeypatch):
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse({}))
    assert client.geocode_city("Xyzzy") is None


def test_corrupted_json_falls_back_to_mock(client, monkeypatch):
    class BadJson(FakeResponse):
        def json(self):
            raise ValueError("Expecting value")

    monkeypatch.setattr(client.session, "get", lambda *a, **k: BadJson(None))
    data = client.fetch_weather_and_air_quality(48.85, 2.35)
    assert data["source"] == "mock"


def test_mock_data_is_stable_within_the_hour(client):
    first = client.fetch_weather_and_air_quality(48.85, 2.35, mock_mode=True)
    second = client.fetch_weather_and_air_quality(48.85, 2.35, mock_mode=True)
    assert first == second
