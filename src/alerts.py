"""Alert engine: detects WHO threshold violations and heatwaves."""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from src.config import HEATWAVE, THRESHOLDS
from src.data_processing import DataProcessor
from src.models import Alert


@dataclass(frozen=True)
class AlertRule:
    """Threshold rule applied to the rolling mean of one pollutant column."""
    column: str
    threshold_key: str
    name: str


ALERT_RULES = [
    AlertRule("pm2_5", "pm2_5", "PM2.5"),
    AlertRule("pm10", "pm10", "PM10"),
    AlertRule("nitrogen_dioxide", "no2", "NO2"),
    AlertRule("ozone", "o3", "O3"),
    AlertRule("sulphur_dioxide", "so2", "SO2"),
    AlertRule("carbon_monoxide", "co", "CO"),
]


class AlertEngine:
    """Rule engine generating alerts from the observations and the temperature forecasts."""

    @staticmethod
    def detect_alerts(df: pd.DataFrame, rules: List[AlertRule] = ALERT_RULES) -> List[Alert]:
        """Returns the pollution and heatwave alerts. Danger alerts come first."""
        if df.empty:
            return []

        alerts = [alert for rule in rules if (alert := AlertEngine.check_pollution(df, rule))]
        heat_alert = AlertEngine.check_heatwave(df)
        if heat_alert:
            alerts.append(heat_alert)
        return sorted(alerts, key=lambda a: a.level != "danger")

    @staticmethod
    def check_pollution(df: pd.DataFrame, rule: AlertRule) -> Optional[Alert]:
        """
        Compares the mean concentration over the WHO averaging period (24 h, 8 h for ozone)
        to the guideline value (warning) and to the interim target (danger).
        """
        threshold = THRESHOLDS[rule.threshold_key]
        hours, unit = threshold["hours"], threshold["unit"]
        mean = DataProcessor.rolling_mean(df, rule.column, hours)
        if pd.isna(mean):
            return None

        if mean >= threshold["danger"]:
            return Alert("danger", f"Alerte Pic de Pollution {rule.name} : moyenne {hours} h {mean:.1f} {unit} "
                                   f"(objectif intermédiaire OMS : {threshold['danger']:g} {unit})")
        if mean >= threshold["warning"]:
            return Alert("warning", f"Vigilance Pollution {rule.name} : moyenne {hours} h {mean:.1f} {unit} "
                                    f"(valeur guide OMS : {threshold['warning']:g} {unit})")
        return None

    @staticmethod
    def check_heatwave(df: pd.DataFrame) -> Optional[Alert]:
        """
        Heatwave detection with the Météo-France method: the means over 3 days (today and the
        next 2 forecast days) of the daily min and max temperatures must both reach their thresholds.
        A single hot day only raises a warning.
        """
        if "temperature_2m" not in df.columns:
            return None
        today = DataProcessor.get_latest_observation(df)["datetime"].date()
        days = pd.date_range(today, periods=HEATWAVE["days"]).date
        daily = DataProcessor.compute_daily_summary(df[df["datetime"].dt.date.isin(days)]).dropna(
            subset=["temp_min", "temp_max"])
        if daily.empty:
            return None

        tmin, tmax = HEATWAVE["tmin"], HEATWAVE["tmax"]
        if len(daily) == HEATWAVE["days"]:
            mean_min, mean_max = daily["temp_min"].mean(), daily["temp_max"].mean()
            if mean_min >= tmin and mean_max >= tmax:
                return Alert("danger", f"Alerte Canicule : moyennes sur {len(daily)} jours min {mean_min:.1f} °C "
                                       f"/ max {mean_max:.1f} °C (seuils {tmin:g} / {tmax:g} °C)")

        hottest_day = daily["temp_max"].idxmax()
        if daily.loc[hottest_day, "temp_max"] >= tmax:
            return Alert("warning", f"Vigilance Forte Chaleur : {daily.loc[hottest_day, 'temp_max']:.1f} °C "
                                    f"le {hottest_day:%d/%m} (seuil {tmax:g} °C)")
        return None
