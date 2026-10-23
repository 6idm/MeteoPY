import numpy as np
import pandas as pd
import pytest

from src.data_processing import DataProcessor


@pytest.fixture
def mock_df() -> pd.DataFrame:
    df = pd.DataFrame({
        "time": ["2026-01-01T00:00", "2026-01-01T01:00"],
        "temperature_2m": [21.0, 40.0],
        "apparent_temperature": [21.0, 42.0],
        "relative_humidity_2m": [50.0, 20.0],
        "pm2_5": [10.0, 30.0],
        "pm10": [20.0, 55.0],
        "nitrogen_dioxide": [15.0, 60.0],
        "us_aqi": [40.0, 90.0],
    })
    df["datetime"] = pd.to_datetime(df["time"])
    return df


@pytest.fixture
def hourly_df() -> pd.DataFrame:
    """Two days of hourly data: temperature rises by 1 °C per hour, constant AQI."""
    times = pd.date_range("2026-01-01", periods=48, freq="h")
    return pd.DataFrame({
        "datetime": times,
        "temperature_2m": np.arange(48, dtype=float),
        "precipitation": [1.0] * 48,
        "us_aqi": [50.0] * 48,
    })


def test_process_raw_api_data_merges_on_time():
    raw = {
        "weather": {"hourly": {"time": ["2026-01-01T01:00", "2026-01-01T00:00"], "temperature_2m": [2.0, 1.0]}},
        "air_quality": {"hourly": {"time": ["2026-01-01T00:00", "2026-01-01T01:00"], "pm2_5": [5.0, 6.0]}},
    }
    df = DataProcessor.process_raw_api_data(raw)
    assert list(df["temperature_2m"]) == [1.0, 2.0]
    assert list(df["pm2_5"]) == [5.0, 6.0]
    assert not df["is_forecast"].any()


def test_process_raw_api_data_empty_input():
    assert DataProcessor.process_raw_api_data({}).empty


def test_clean_data_removes_invalid_values_and_fills_short_gaps():
    df = pd.DataFrame({
        "time": ["t0", "t1", "t2", "t2"],
        "datetime": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 01:00", "2026-01-01 02:00", "2026-01-01 02:00"]),
        "relative_humidity_2m": [50, 150, 70, 70],
        "pm2_5": [10, -5, "abc", 30],
    })
    cleaned = DataProcessor.clean_data(df)
    assert len(cleaned) == 3
    assert cleaned["relative_humidity_2m"].tolist() == [50, 60, 70]
    assert cleaned["pm2_5"].tolist() == [10, 20, 30]


def test_health_index_calculation(mock_df):
    scores = DataProcessor.calculate_custom_health_index(mock_df)
    assert len(scores) == 2
    assert scores.iloc[0] > scores.iloc[1]
    assert scores.between(0, 100).all()


def test_health_index_uses_apparent_temperature(mock_df):
    comfortable = mock_df.iloc[[0]].copy()
    uncomfortable = comfortable.copy()
    uncomfortable["apparent_temperature"] = 35.0
    assert (DataProcessor.calculate_custom_health_index(comfortable).iloc[0]
            > DataProcessor.calculate_custom_health_index(uncomfortable).iloc[0])


def test_latest_observation_skips_future_nan_rows(mock_df):
    future = mock_df.iloc[[-1]].copy()
    future["datetime"] = pd.Timestamp("2100-01-01")
    future[["pm2_5", "us_aqi"]] = np.nan
    latest = DataProcessor.get_latest_observation(pd.concat([mock_df, future]))
    assert latest["us_aqi"] == 90.0


def test_compute_statistics_over_last_hours(hourly_df):
    stats = DataProcessor.compute_statistics(hourly_df, ["temperature_2m"], hours=24)
    row = stats.loc["temperature_2m"]
    assert row["Min"] == 24 and row["Max"] == 47
    assert row["Moyenne"] == pytest.approx(35.5)
    assert row["Médiane"] == pytest.approx(35.5)


def test_compute_trend_detects_rise_and_stability(hourly_df):
    rise = DataProcessor.compute_trend(hourly_df, "temperature_2m", hours=24)
    assert rise["direction"] == "hausse"
    assert rise["variation"] == pytest.approx(23)
    assert rise["slope_per_day"] == pytest.approx(24)
    assert DataProcessor.compute_trend(hourly_df, "us_aqi", hours=24)["direction"] == "stable"


def test_compute_trend_without_data():
    df = pd.DataFrame({"datetime": pd.to_datetime(["2026-01-01"]), "temperature_2m": [10.0]})
    assert DataProcessor.compute_trend(df, "temperature_2m", 24)["direction"] == "indisponible"


def test_daily_summary(hourly_df):
    daily = DataProcessor.compute_daily_summary(hourly_df)
    assert len(daily) == 2
    assert daily.iloc[0]["temp_min"] == 0 and daily.iloc[0]["temp_max"] == 23
    assert daily.iloc[1]["precipitation_totale"] == 24


@pytest.mark.parametrize("aqi, expected", [(30, "Bon"), (100, "Modéré"), (180, "Mauvais"), (np.nan, "Indisponible")])
def test_aqi_category(aqi, expected):
    assert DataProcessor.get_aqi_category(aqi)["label"] == expected


def test_compute_variation(hourly_df):
    assert DataProcessor.compute_variation(hourly_df, "temperature_2m", 24) == 24
    assert np.isnan(DataProcessor.compute_variation(hourly_df, "temperature_2m", 100))


def test_rolling_mean(hourly_df):
    assert DataProcessor.rolling_mean(hourly_df, "temperature_2m", 24) == pytest.approx(35.5)
    assert np.isnan(DataProcessor.rolling_mean(hourly_df, "unknown", 24))


def test_rolling_mean_requires_enough_data(hourly_df):
    df = hourly_df.copy()
    df.loc[df.index[-10:], "temperature_2m"] = np.nan  # 14 values out of 24 < 75 %
    assert np.isnan(DataProcessor.rolling_mean(df, "temperature_2m", 24, end=df["datetime"].iloc[-1]))


def test_daily_summary_with_missing_values(hourly_df):
    df = hourly_df.copy()
    df.loc[df.index[:24], "precipitation"] = np.nan
    daily = DataProcessor.compute_daily_summary(df)
    assert np.isnan(daily.iloc[0]["precipitation_totale"])
    assert daily.iloc[1]["precipitation_totale"] == 24
