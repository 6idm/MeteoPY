import numpy as np
import pandas as pd
import pytest

from src.alerts import AlertEngine
from src.models import Alert


def hourly(days: int = 1, start: str = "2026-07-01", **columns) -> pd.DataFrame:
    """Hourly DataFrame; each column is a constant or a list of 24 * days values."""
    times = pd.date_range(start, periods=24 * days, freq="h")
    return pd.DataFrame({"datetime": times, **columns})


def heat_df(daily_temps):
    """One row per hour; each day is (min, max). Air quality is only observed on the first day,
    like the API data where the next days are temperature forecasts."""
    temps = [t for tmin, tmax in daily_temps for t in [tmin] * 12 + [tmax] * 12]
    pm = [5.0] * 24 + [np.nan] * 24 * (len(daily_temps) - 1)
    return hourly(len(daily_temps), temperature_2m=temps, pm2_5=pm)


def test_pollution_alert_uses_24h_mean_not_latest_value():
    df = hourly(pm2_5=[10.0] * 23 + [100.0])  # mean 13.75 < 15 despite a 100 µg/m³ peak
    assert AlertEngine.detect_alerts(df) == []


def test_pollution_danger_alert():
    alerts = AlertEngine.detect_alerts(hourly(nitrogen_dioxide=60.0))
    assert alerts == [Alert("danger", "Alerte Pic de Pollution NO2 : moyenne 24 h 60.0 µg/m³ "
                                      "(objectif intermédiaire OMS : 50 µg/m³)")]


def test_pollution_warning_alert():
    alerts = AlertEngine.detect_alerts(hourly(pm2_5=20.0))
    assert [a.level for a in alerts] == ["warning"]
    assert alerts[0].message.startswith("Vigilance Pollution PM2.5 : moyenne 24 h 20.0")


def test_ozone_uses_8h_mean():
    df = hourly(ozone=[50.0] * 16 + [150.0] * 8)
    alerts = AlertEngine.detect_alerts(df)
    assert [a.level for a in alerts] == ["danger"]
    assert "moyenne 8 h 150.0" in alerts[0].message


def test_carbon_monoxide_alert():
    alerts = AlertEngine.detect_alerts(hourly(carbon_monoxide=5000.0))
    assert [a.level for a in alerts] == ["warning"]
    assert "CO" in alerts[0].message


def test_no_pollution_alert_without_enough_data():
    df = hourly(pm2_5=[np.nan] * 14 + [60.0] * 10)  # 10 hourly values out of 24
    assert AlertEngine.detect_alerts(df) == []


def test_heatwave_alert_on_three_hot_days():
    alerts = AlertEngine.detect_alerts(heat_df([(22, 35), (23, 36), (21, 34)]))
    assert [a.level for a in alerts] == ["danger"]
    assert alerts[0].message.startswith("Alerte Canicule : moyennes sur 3 jours min 22.0 °C / max 35.0 °C")


def test_single_hot_day_is_only_a_warning():
    alerts = AlertEngine.detect_alerts(heat_df([(18, 25), (22, 36), (17, 26)]))
    assert alerts == [Alert("warning", "Vigilance Forte Chaleur : 36.0 °C le 02/07 (seuil 33 °C)")]


def test_hot_days_with_cool_nights_are_not_a_heatwave():
    alerts = AlertEngine.detect_alerts(heat_df([(15, 35), (16, 36), (15, 34)]))
    assert [a.level for a in alerts] == ["warning"]


def test_no_heat_alert_in_normal_conditions():
    assert AlertEngine.detect_alerts(heat_df([(12, 24), (13, 25), (12, 23)])) == []


def test_danger_alerts_come_first():
    df = hourly(pm2_5=20.0, nitrogen_dioxide=60.0)
    assert [a.level for a in AlertEngine.detect_alerts(df)] == ["danger", "warning"]


@pytest.mark.parametrize("df", [pd.DataFrame(), hourly(relative_humidity_2m=50.0)])
def test_no_alert_without_data(df):
    assert AlertEngine.detect_alerts(df) == []
