import datetime
import sqlite3

import pytest
import requests

from src.api_client import WeatherAPIClient


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
    assert len(data["weather"]["hourly"]["time"]) == 24 * 7
    assert "pm2_5" in data["air_quality"]["hourly"]


def test_network_error_falls_back_to_mock(client, monkeypatch):
    def fail(*args, **kwargs):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fail)
    data = client.fetch_weather_and_air_quality(48.85, 2.35)
    assert "hourly" in data["weather"]


def test_cached_response_avoids_api_call(client, monkeypatch):
    client._set_cached_data("data_48.85_2.35", {"weather": {}, "air_quality": {}, "cached": True})

    def fail(*args, **kwargs):
        raise AssertionError("API should not be called")

    monkeypatch.setattr(requests, "get", fail)
    assert client.fetch_weather_and_air_quality(48.85, 2.35)["cached"] is True
