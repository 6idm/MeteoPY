"""Alert engine: detects WHO threshold violations."""
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

from src.config import THRESHOLDS
from src.data_processing import DataProcessor


@dataclass(frozen=True)
class AlertRule:
    """Threshold rule applied to one column of the latest observation."""
    column: str
    threshold_key: str
    warning_label: str
    danger_label: str


ALERT_RULES = [
    AlertRule("pm2_5", "pm2_5", "Vigilance Pollution PM2.5", "Alerte Pic de Pollution PM2.5"),
    AlertRule("pm10", "pm10", "Vigilance Pollution PM10", "Alerte Pic de Pollution PM10"),
    AlertRule("nitrogen_dioxide", "no2", "Vigilance Pollution NO2", "Alerte Pic de Pollution NO2"),
    AlertRule("ozone", "o3", "Vigilance Pollution O3", "Alerte Pic de Pollution O3"),
    AlertRule("sulphur_dioxide", "so2", "Vigilance Pollution SO2", "Alerte Pic de Pollution SO2"),
    AlertRule("temperature_2m", "temp_max", "Vigilance Forte Chaleur", "Alerte Canicule"),
]


class AlertEngine:
    """
    Rule engine generating alerts from the latest observation.
    Author: Student B (Data Analyst)
    """

    @staticmethod
    def detect_alerts(df: pd.DataFrame, rules: List[AlertRule] = ALERT_RULES) -> List[Dict[str, str]]:
        """Scans the latest observation for threshold violations. Danger alerts come first."""
        alerts = []
        if df.empty:
            return alerts

        latest = DataProcessor.get_latest_observation(df)

        for rule in rules:
            value = latest.get(rule.column)
            if value is None or pd.isna(value):
                continue
            threshold = THRESHOLDS[rule.threshold_key]
            unit = threshold["unit"]

            if value >= threshold["danger"]:
                alerts.append({
                    "level": "danger",
                    "message": f"{rule.danger_label} : {value:.1f} {unit} (seuil : {threshold['danger']} {unit})"
                })
            elif value >= threshold["warning"]:
                alerts.append({
                    "level": "warning",
                    "message": f"{rule.warning_label} : {value:.1f} {unit} (seuil : {threshold['warning']} {unit})"
                })

        return sorted(alerts, key=lambda a: a["level"] != "danger")
