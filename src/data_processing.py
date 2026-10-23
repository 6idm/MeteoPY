"""Data transformation and business calculations (pandas)."""
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from src.config import AQI_CATEGORIES, MIN_DATA_COVERAGE, THRESHOLDS

# Physically valid ranges used to discard corrupted values
VALID_RANGES = {
    "relative_humidity_2m": (0, 100),
    "cloud_cover": (0, 100),
    "wind_direction_10m": (0, 360),
    "precipitation": (0, None),
    "wind_speed_10m": (0, None),
    "pm2_5": (0, None),
    "pm10": (0, None),
    "nitrogen_dioxide": (0, None),
    "ozone": (0, None),
    "sulphur_dioxide": (0, None),
    "carbon_monoxide": (0, None),
    "us_aqi": (0, 500),
}


class DataProcessor:
    """
    Data Transformation, Statistics and Calculations.
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
        return DataProcessor.clean_data(df)

    @staticmethod
    def clean_data(df: pd.DataFrame) -> pd.DataFrame:
        """
        Cleans the merged DataFrame: removes duplicated timestamps, converts values to numbers,
        discards out-of-range values and fills short gaps (max 2 h) by interpolation.
        Also flags forecast rows (after the current UTC hour).
        """
        df = df.drop_duplicates(subset="datetime", keep="last").reset_index(drop=True)
        value_cols = [c for c in df.columns if c not in ("time", "datetime")]
        df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")

        for col, (low, high) in VALID_RANGES.items():
            if col in df.columns:
                out_of_range = (df[col] < low) if low is not None else pd.Series(False, index=df.index)
                if high is not None:
                    out_of_range |= df[col] > high
                df.loc[out_of_range, col] = np.nan

        df[value_cols] = df[value_cols].interpolate(limit=2, limit_area="inside")
        df["is_forecast"] = df["datetime"] > pd.Timestamp.now(tz="UTC").tz_localize(None)
        return df

    @staticmethod
    def get_latest_observation(df: pd.DataFrame) -> pd.Series:
        """
        Returns the most recent row that is not in the future and has complete key values.
        The API series also contains forecasts (with NaN for air quality), so df.iloc[-1]
        is not the current state.
        """
        key_cols = [c for c in ("temperature_2m", "relative_humidity_2m", "pm2_5", "nitrogen_dioxide", "us_aqi")
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
    def get_window(df: pd.DataFrame, hours: int, end: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """Returns the rows of the `hours` hours ending at `end` (default: latest observation)."""
        if df.empty:
            return df
        if end is None:
            end = DataProcessor.get_latest_observation(df)["datetime"]
        return df[(df["datetime"] > end - pd.Timedelta(hours=hours)) & (df["datetime"] <= end)]

    @staticmethod
    def rolling_mean(df: pd.DataFrame, column: str, hours: int, end: Optional[pd.Timestamp] = None,
                     min_coverage: float = MIN_DATA_COVERAGE) -> float:
        """
        Mean of a column over the last `hours` hours of observations.
        Returns NaN when less than `min_coverage` of the hourly values are available.
        """
        if df.empty or column not in df.columns:
            return np.nan
        values = DataProcessor.get_window(df, hours, end)[column].dropna()
        if len(values) < min_coverage * hours:
            return np.nan
        return float(values.mean())

    @staticmethod
    def compute_statistics(df: pd.DataFrame, columns: List[str], hours: int,
                           end: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """
        Computes mean / median / min / max / standard deviation of each column
        over the last `hours` hours of observations.
        """
        window = DataProcessor.get_window(df, hours, end)
        columns = [c for c in columns if c in window.columns]
        stats = window[columns].agg(["mean", "median", "min", "max", "std"]).T
        stats.columns = ["Moyenne", "Médiane", "Min", "Max", "Écart-type"]
        return stats.round(2)

    @staticmethod
    def compute_trend(df: pd.DataFrame, column: str, hours: int,
                      end: Optional[pd.Timestamp] = None) -> Dict[str, Any]:
        """
        Computes the evolution trend of a column over the last `hours` hours using a
        least-squares linear regression.
        Returns the total variation over the window, the slope per day and a direction
        ("hausse", "baisse" or "stable": variation smaller than 5% of the mean).
        """
        window = DataProcessor.get_window(df, hours, end)[["datetime", column]].dropna()
        if len(window) < 2:
            return {"variation": np.nan, "slope_per_day": np.nan, "direction": "indisponible"}

        x_hours = (window["datetime"] - window["datetime"].iloc[0]).dt.total_seconds() / 3600
        slope_per_hour = np.polyfit(x_hours, window[column], 1)[0]
        variation = slope_per_hour * x_hours.iloc[-1]

        tolerance = max(0.05 * abs(window[column].mean()), 0.1)
        if abs(variation) < tolerance:
            direction = "stable"
        else:
            direction = "hausse" if variation > 0 else "baisse"

        return {
            "variation": round(float(variation), 2),
            "slope_per_day": round(float(slope_per_hour * 24), 2),
            "direction": direction,
        }

    @staticmethod
    def compute_variation(df: pd.DataFrame, column: str, hours: int) -> float:
        """Difference between the latest observed value and the value `hours` hours earlier."""
        if df.empty:
            return np.nan
        latest = DataProcessor.get_latest_observation(df)
        previous = df.loc[df["datetime"] == latest["datetime"] - pd.Timedelta(hours=hours), column]
        if previous.empty or pd.isna(previous.iloc[0]) or pd.isna(latest[column]):
            return np.nan
        return round(float(latest[column] - previous.iloc[0]), 2)

    @staticmethod
    def compute_daily_summary(df: pd.DataFrame) -> pd.DataFrame:
        """Aggregates hourly data per day: min/max/mean temperature, precipitation total, mean AQI."""
        if df.empty:
            return pd.DataFrame()
        grouped = df.groupby(df["datetime"].dt.date)
        summary = pd.DataFrame({
            "temp_min": grouped["temperature_2m"].min(),
            "temp_max": grouped["temperature_2m"].max(),
            "temp_moyenne": grouped["temperature_2m"].mean(),
        })
        if "precipitation" in df.columns:
            summary["precipitation_totale"] = grouped["precipitation"].sum(min_count=1)
        if "us_aqi" in df.columns:
            summary["aqi_moyen"] = grouped["us_aqi"].mean()
        summary.index.name = "date"
        return summary.round(1)

    @staticmethod
    def calculate_custom_health_index(df: pd.DataFrame) -> pd.Series:
        """
        Calculates a custom composite Comfort/Health Score (0-100 scale). Higher is better.
        Combines apparent temperature (falls back to air temperature), humidity and pollution
        levels (PM2.5 and NO2 relative to their WHO guideline values).
        """
        temp = df["apparent_temperature"] if "apparent_temperature" in df.columns else df["temperature_2m"]
        humidity = df["relative_humidity_2m"]

        # Penalty factors based on optimal comfort conditions
        temp_penalty = np.abs(temp - 21.0) * 1.5
        humidity_penalty = np.abs(humidity - 50.0) * 0.3
        pollution_penalty = df["pm2_5"] / THRESHOLDS["pm2_5"]["warning"] * 12
        if "nitrogen_dioxide" in df.columns:
            pollution_penalty = pollution_penalty + df["nitrogen_dioxide"] / THRESHOLDS["no2"]["warning"] * 6

        score = 100 - (temp_penalty + humidity_penalty + pollution_penalty)
        return score.clip(0, 100).round(1)

    @staticmethod
    def get_aqi_category(aqi: float) -> Dict[str, str]:
        """Returns the US AQI category label and color for an AQI value."""
        if pd.isna(aqi):
            return {"label": "Indisponible", "color": "#9e9e9e"}
        for upper, label, color in AQI_CATEGORIES:
            if aqi <= upper:
                return {"label": label, "color": color}
        return {"label": AQI_CATEGORIES[-1][1], "color": AQI_CATEGORIES[-1][2]}
