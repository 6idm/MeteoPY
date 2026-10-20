import numpy as np
import pandas as pd
import pytest

from src.alerts import AlertEngine
from src.data_processing import DataProcessor


@pytest.fixture
def mock_df() -> pd.DataFrame:
    df = pd.DataFrame({
        "time": ["2026-01-01T00:00", "2026-01-01T01:00"],
        "temperature_2m": [21.0, 40.0],
        "relativehumidity_2m": [50.0, 20.0],
        "pm2_5": [10.0, 30.0],
        "pm10": [20.0, 55.0],
        "nitrogen_dioxide": [15.0, 60.0],
        "us_aqi": [40.0, 90.0],
    })
    df["datetime"] = pd.to_datetime(df["time"])
    return df


def test_process_raw_api_data_merges_on_time():
    raw = {
        "weather": {"hourly": {"time": ["2026-01-01T01:00", "2026-01-01T00:00"], "temperature_2m": [2.0, 1.0]}},
        "air_quality": {"hourly": {"time": ["2026-01-01T00:00", "2026-01-01T01:00"], "pm2_5": [5.0, 6.0]}},
    }
    df = DataProcessor.process_raw_api_data(raw)
    assert list(df["temperature_2m"]) == [1.0, 2.0]
    assert list(df["pm2_5"]) == [5.0, 6.0]


def test_process_raw_api_data_empty_input():
    assert DataProcessor.process_raw_api_data({}).empty


def test_health_index_calculation(mock_df):
    scores = DataProcessor.calculate_custom_health_index(mock_df)
    assert len(scores) == 2
    assert scores.iloc[0] > scores.iloc[1]
    assert scores.between(0, 100).all()


def test_latest_observation_skips_future_nan_rows(mock_df):
    future = mock_df.iloc[[-1]].copy()
    future["datetime"] = pd.Timestamp("2100-01-01")
    future[["pm2_5", "us_aqi"]] = np.nan
    latest = DataProcessor.get_latest_observation(pd.concat([mock_df, future]))
    assert latest["us_aqi"] == 90.0


def test_alerts_detection(mock_df):
    alerts = AlertEngine.detect_alerts(mock_df)
    levels = {a["level"] for a in alerts}
    assert len(alerts) == 3
    assert levels == {"danger", "warning"}


def test_no_alert_when_values_are_normal(mock_df):
    assert AlertEngine.detect_alerts(mock_df.iloc[[0]]) == []


def test_no_alert_on_empty_dataframe():
    assert AlertEngine.detect_alerts(pd.DataFrame()) == []
