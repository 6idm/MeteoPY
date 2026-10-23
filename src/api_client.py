"""Open-Meteo API client with SQLite local cache, geocoding and offline mock data."""
import datetime
import json
import logging
import sqlite3
from dataclasses import asdict
from typing import Any, Dict, Optional

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import (
    AIR_QUALITY_VARIABLES,
    CACHE_DB,
    CACHE_TTL_MINUTES,
    FORECAST_DAYS,
    PAST_DAYS,
    REQUEST_TIMEOUT_SECONDS,
    WEATHER_VARIABLES,
)
from src.models import City

logger = logging.getLogger(__name__)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


class WeatherAPIClient:
    """
    Handles API calls to Open-Meteo REST APIs and manages SQLite local caching.
    """

    def __init__(self, db_path: str = CACHE_DB):
        self.db_path = db_path
        self.session = self._build_session()
        self._init_db()

    @staticmethod
    def _build_session() -> requests.Session:
        """HTTP session retrying transient errors (rate limit, 5xx) with exponential backoff."""
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET"])
        session = requests.Session()
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def _init_db(self) -> None:
        """Initializes SQLite cache database table."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_cache (
                        key TEXT PRIMARY KEY,
                        response TEXT,
                        timestamp DATETIME
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")

    def _get_cached_data(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached json response if within TTL limit."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT response, timestamp FROM api_cache WHERE key = ?", (key,))
                row = cursor.fetchone()

                if row:
                    cached_response, timestamp_str = row
                    timestamp = datetime.datetime.fromisoformat(timestamp_str)
                    if datetime.datetime.now() - timestamp < datetime.timedelta(minutes=CACHE_TTL_MINUTES):
                        logger.info(f"Cache hit for key: {key}")
                        return json.loads(cached_response)
        except Exception as e:
            logger.warning(f"Failed to read cache for key {key}: {e}")
        return None

    def _set_cached_data(self, key: str, data: Dict[str, Any]) -> None:
        """Saves API response to local SQLite cache."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now_str = datetime.datetime.now().isoformat()
                cursor.execute("""
                    INSERT OR REPLACE INTO api_cache (key, response, timestamp)
                    VALUES (?, ?, ?)
                """, (key, json.dumps(data), now_str))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to write cache for key {key}: {e}")

    def geocode_city(self, name: str) -> Optional[City]:
        """
        Resolves a city name to coordinates with the Open-Meteo geocoding API.
        Returns None if the city is not found or the API is unreachable.
        """
        name = name.strip()
        if not name:
            return None

        cache_key = f"geo_{name.lower()}"
        cached = self._get_cached_data(cache_key)
        if cached:
            return City(**cached)

        try:
            res = self.session.get(
                GEOCODING_URL, params={"name": name, "count": 1, "language": "fr"},
                timeout=REQUEST_TIMEOUT_SECONDS
            )
            res.raise_for_status()
            results = res.json().get("results") or []
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.error(f"Geocoding failed for '{name}': {e}")
            return None

        if not results:
            return None

        first = results[0]
        try:
            city = City(first["name"], first["latitude"], first["longitude"], first.get("country", ""))
        except KeyError as e:
            logger.error(f"Incomplete geocoding result for '{name}': missing {e}")
            return None
        self._set_cached_data(cache_key, asdict(city))
        return city

    def fetch_weather_and_air_quality(self, lat: float, lon: float, mock_mode: bool = False) -> Dict[str, Any]:
        """
        Fetches combined weather and air quality data (past days + forecast, hourly, UTC)
        from Open-Meteo or local mock generator.
        The "source" key of the result tells where the data comes from: "api", "cache" or "mock".
        """
        cache_key = f"data_v2_{lat}_{lon}"

        if mock_mode:
            return self._generate_mock_data(lat, lon)

        cached_data = self._get_cached_data(cache_key)
        if cached_data:
            return {**cached_data, "source": "cache"}

        common = {
            "latitude": lat, "longitude": lon, "timezone": "UTC",
            "past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS,
        }
        weather_params = {**common, "hourly": ",".join(WEATHER_VARIABLES)}
        air_quality_params = {**common, "hourly": ",".join(AIR_QUALITY_VARIABLES)}

        try:
            logger.info(f"Requesting remote APIs for coordinates ({lat}, {lon})...")
            weather_res = self.session.get(WEATHER_URL, params=weather_params, timeout=REQUEST_TIMEOUT_SECONDS)
            air_res = self.session.get(AIR_QUALITY_URL, params=air_quality_params, timeout=REQUEST_TIMEOUT_SECONDS)

            weather_res.raise_for_status()
            air_res.raise_for_status()

            combined = {
                "weather": weather_res.json(),
                "air_quality": air_res.json()
            }
            self._set_cached_data(cache_key, combined)
            return {**combined, "source": "api"}

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}. Falling back to mock data.")
            return self._generate_mock_data(lat, lon)
        except ValueError as e:
            logger.error(f"Invalid JSON received from API: {e}. Falling back to mock data.")
            return self._generate_mock_data(lat, lon)

    def _generate_mock_data(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fallback mock data generator for disconnected mode or testing (same layout as the API).
        Values are seeded by location and current hour so they stay stable between page refreshes.
        """
        hours = 24 * (PAST_DAYS + FORECAST_DAYS)
        now = datetime.datetime.now(datetime.timezone.utc)
        rng = np.random.default_rng([int(abs(lat) * 1e4), int(abs(lon) * 1e4), int(now.timestamp() // 3600)])
        start = now.replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        ) - datetime.timedelta(days=PAST_DAYS)
        times = [(start + datetime.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)]

        # Daily temperature cycle: coolest around 4h, warmest around 16h
        hour_of_day = np.arange(hours) % 24
        temperature = 18 + 6 * np.sin((hour_of_day - 10) / 24 * 2 * np.pi) + rng.normal(0, 1.5, hours)
        humidity = np.clip(70 - 2 * (temperature - 18) + rng.normal(0, 5, hours), 20, 100)
        wind = rng.uniform(2, 30, hours)

        return {
            "source": "mock",
            "weather": {
                "hourly": {
                    "time": times,
                    "temperature_2m": temperature.round(1).tolist(),
                    "apparent_temperature": (temperature - wind * 0.1).round(1).tolist(),
                    "relative_humidity_2m": humidity.round(0).tolist(),
                    "surface_pressure": rng.uniform(1000, 1025, hours).round(1).tolist(),
                    "wind_speed_10m": wind.round(1).tolist(),
                    "wind_direction_10m": rng.uniform(0, 360, hours).round(0).tolist(),
                    "cloud_cover": rng.uniform(0, 100, hours).round(0).tolist(),
                    "precipitation": np.where(rng.random(hours) < 0.15,
                                              rng.uniform(0.1, 4, hours), 0.0).round(1).tolist()
                }
            },
            "air_quality": {
                "hourly": {
                    "time": times,
                    "pm2_5": rng.uniform(5, 35, hours).tolist(),
                    "pm10": rng.uniform(10, 60, hours).tolist(),
                    "nitrogen_dioxide": rng.uniform(10, 55, hours).tolist(),
                    "ozone": rng.uniform(20, 120, hours).tolist(),
                    "sulphur_dioxide": rng.uniform(1, 15, hours).tolist(),
                    "carbon_monoxide": rng.uniform(100, 500, hours).tolist(),
                    "us_aqi": rng.integers(15, 160, hours).tolist()
                }
            }
        }
