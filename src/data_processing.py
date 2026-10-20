"""Data transformation and business calculations (pandas)."""
from typing import Any, Dict

import numpy as np
import pandas as pd


class DataProcessor:
    """
    Data Transformation and Calculations.
    Author: Student B (Data Analyst)
    """

    @staticmethod
    def process_raw_api_data(raw_data: Dict[str, Any]) -> pd.DataFrame:
        """Transforms raw API responses into a clean Pandas DataFrame."""
        w_hourly = raw_data.get("weather", {}).get("hourly", {})
        a_hourly = raw_data.get("air_quality", {}).get("hourly", {})

        df_weather = pd.DataFrame(w_hourly)
        df_air = pd.DataFrame(a_hourly)

        if df_weather.empty or df_air.empty:
            return pd.DataFrame()

        df = pd.merge(df_weather, df_air, on="time", how="inner")
        df["datetime"] = pd.to_datetime(df["time"])
        df.sort_values("datetime", inplace=True)
        return df

    @staticmethod
    def get_latest_observation(df: pd.DataFrame) -> pd.Series:
        """
        Returns the most recent row that is not in the future and has complete key values.
        The API series also contains forecasts (with NaN for air quality), so df.iloc[-1]
        is not the current state.
        """
        key_cols = [c for c in ("temperature_2m", "relativehumidity_2m", "pm2_5", "nitrogen_dioxide", "us_aqi")
                    if c in df.columns]
        now_utc = pd.Timestamp.now(tz="UTC").tz_localize(None)
        valid = df.dropna(subset=key_cols)
        if "datetime" in valid.columns:
            past = valid[valid["datetime"] <= now_utc]
            if not past.empty:
                valid = past
        if valid.empty:
            return df.iloc[-1]
        return valid.iloc[-1]

    @staticmethod
    def calculate_custom_health_index(df: pd.DataFrame) -> pd.Series:
        """
        Calculates a custom composite Comfort/Health Score (0-100 scale).
        Higher is better.
        """
        temp = df["temperature_2m"]
        humidity = df["relativehumidity_2m"]
        pm2_5 = df["pm2_5"]

        # Penalty factors based on optimal comfort conditions
        temp_penalty = np.abs(temp - 21.0) * 1.5
        humidity_penalty = np.abs(humidity - 50.0) * 0.3
        pollution_penalty = pm2_5 * 1.2

        score = 100 - (temp_penalty + humidity_penalty + pollution_penalty)
        return score.clip(0, 100).round(1)
