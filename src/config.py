"""Shared configuration: paths, cache settings, API variables, cities and alert thresholds."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

CACHE_DB = os.getenv("METEO_CACHE_DB", str(DATA_DIR / "data_cache.db"))
CACHE_TTL_MINUTES = int(os.getenv("METEO_CACHE_TTL_MINUTES", "30"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("METEO_REQUEST_TIMEOUT_SECONDS", "5"))

PAST_DAYS = 7
FORECAST_DAYS = 3

WEATHER_VARIABLES = [
    "temperature_2m", "apparent_temperature", "relative_humidity_2m", "surface_pressure",
    "wind_speed_10m", "wind_direction_10m", "cloud_cover", "precipitation"
]
AIR_QUALITY_VARIABLES = [
    "pm2_5", "pm10", "nitrogen_dioxide", "ozone", "sulphur_dioxide", "carbon_monoxide", "us_aqi"
]

# Display labels and units for every metric of the dashboard
METRICS = {
    "temperature_2m": ("Température", "°C"),
    "apparent_temperature": ("Température ressentie", "°C"),
    "relative_humidity_2m": ("Humidité", "%"),
    "surface_pressure": ("Pression", "hPa"),
    "wind_speed_10m": ("Vent", "km/h"),
    "wind_direction_10m": ("Direction du vent", "°"),
    "cloud_cover": ("Couverture nuageuse", "%"),
    "precipitation": ("Précipitations", "mm"),
    "pm2_5": ("PM2.5", "µg/m³"),
    "pm10": ("PM10", "µg/m³"),
    "nitrogen_dioxide": ("NO2", "µg/m³"),
    "ozone": ("O3", "µg/m³"),
    "sulphur_dioxide": ("SO2", "µg/m³"),
    "carbon_monoxide": ("CO", "µg/m³"),
    "us_aqi": ("Indice AQI (US)", ""),
    "health_score": ("Score Confort", "/100"),
}

DEFAULT_CITIES = {
    "Paris": {"lat": 48.8566, "lon": 2.3522},
    "Lyon": {"lat": 45.7640, "lon": 4.8357},
    "Marseille": {"lat": 43.2965, "lon": 5.3698},
    "London": {"lat": 51.5074, "lon": -0.1278},
    "Madrid": {"lat": 40.4168, "lon": -3.7038}
}

# Thresholds for alerts (WHO 2021 guidelines; temperatures from French heatwave vigilance levels)
THRESHOLDS = {
    "pm2_5": {"warning": 15.0, "danger": 25.0, "unit": "µg/m³"},
    "pm10": {"warning": 45.0, "danger": 50.0, "unit": "µg/m³"},
    "no2": {"warning": 25.0, "danger": 50.0, "unit": "µg/m³"},
    "o3": {"warning": 100.0, "danger": 180.0, "unit": "µg/m³"},
    "so2": {"warning": 40.0, "danger": 125.0, "unit": "µg/m³"},
    "temp_max": {"warning": 33.0, "danger": 38.0, "unit": "°C"}
}

# US AQI categories: (upper bound, label, color)
AQI_CATEGORIES = [
    (50, "Bon", "#00e400"),
    (100, "Modéré", "#ffff00"),
    (150, "Mauvais pour les sensibles", "#ff7e00"),
    (200, "Mauvais", "#ff0000"),
    (300, "Très mauvais", "#8f3f97"),
    (float("inf"), "Dangereux", "#7e0023"),
]
