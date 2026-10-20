"""Streamlit user interface (View layer)."""
from typing import Dict, List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.alerts import AlertEngine
from src.api_client import WeatherAPIClient
from src.config import DEFAULT_CITIES, METRICS, THRESHOLDS
from src.data_processing import DataProcessor

POLLUTANTS = ["pm2_5", "pm10", "nitrogen_dioxide", "ozone", "sulphur_dioxide", "carbon_monoxide"]
STAT_WINDOWS = {"6 dernières heures": 6, "24 dernières heures": 24, "3 derniers jours": 72, "7 derniers jours": 168}
WIND_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def label(metric: str) -> str:
    """Returns the display label of a metric with its unit."""
    name, unit = METRICS.get(metric, (metric, ""))
    return f"{name} ({unit})" if unit else name


def wind_cardinal(degrees: float) -> str:
    """Converts a wind direction in degrees to a cardinal point."""
    if pd.isna(degrees):
        return "-"
    return WIND_DIRECTIONS[int((degrees % 360) / 45 + 0.5) % 8]


def fmt(value: float, unit: str = "", decimals: int = 1) -> str:
    """Formats a numeric value, returning N/A for missing data."""
    if pd.isna(value):
        return "N/A"
    return f"{value:.{decimals}f} {unit}".strip()


def load_city_data(lat: float, lon: float, mock_mode: bool) -> pd.DataFrame:
    """
    Fetches, processes and enriches the data of one location (API calls are cached in SQLite).
    The data source ("api", "cache" or "mock") is stored in df.attrs["source"].
    """
    raw_data = WeatherAPIClient().fetch_weather_and_air_quality(lat, lon, mock_mode=mock_mode)
    df = DataProcessor.process_raw_api_data(raw_data)
    if not df.empty:
        df["health_score"] = DataProcessor.calculate_custom_health_index(df)
    df.attrs["source"] = raw_data.get("source", "api")
    return df


def render_sidebar(cities: Dict[str, Dict[str, float]]) -> Dict:
    """Renders the selection panel and returns the user choices."""
    st.sidebar.header("⚙️ Configuration")
    selected_city = st.sidebar.selectbox("Ville", list(cities.keys()))

    with st.sidebar.form("add_city", clear_on_submit=True):
        new_city = st.text_input("Ajouter une ville", placeholder="ex : Bordeaux")
        if st.form_submit_button("Rechercher") and new_city:
            found = WeatherAPIClient().geocode_city(new_city)
            if found:
                cities[f"{found['name']} ({found['country']})"] = {"lat": found["lat"], "lon": found["lon"]}
                st.rerun()
            else:
                st.error(f"Ville « {new_city} » introuvable.")

    mock_mode = st.sidebar.checkbox("Mode Déconnecté / Data Mocked", value=False)
    return {"city": selected_city, "mock_mode": mock_mode}


def render_kpis(df: pd.DataFrame, latest: pd.Series) -> None:
    """Renders the synthetic KPI cards with their 24h variation."""
    today = DataProcessor.compute_daily_summary(df[df["datetime"].dt.date == latest["datetime"].date()])
    precip_24h = DataProcessor.get_window(df, 24)["precipitation"].sum(min_count=1)
    aqi_category = DataProcessor.get_aqi_category(latest["us_aqi"])

    def delta(metric: str) -> str:
        variation = DataProcessor.compute_variation(df, metric, 24)
        return None if pd.isna(variation) else f"{variation:+.1f} en 24h"

    row1 = st.columns(5)
    row1[0].metric("Température", fmt(latest["temperature_2m"], "°C"), delta("temperature_2m"))
    row1[1].metric("Ressentie", fmt(latest["apparent_temperature"], "°C"), delta("apparent_temperature"))
    if not today.empty:
        row1[2].metric("Min / Max du jour",
                       f"{fmt(today['temp_min'].iloc[0], '°C')} / {fmt(today['temp_max'].iloc[0], '°C')}")
    row1[3].metric("Humidité", fmt(latest["relative_humidity_2m"], "%", 0), delta("relative_humidity_2m"),
                   delta_color="off")
    row1[4].metric("Pression", fmt(latest["surface_pressure"], "hPa", 0), delta("surface_pressure"),
                   delta_color="off")

    row2 = st.columns(5)
    row2[0].metric("Vent", f"{fmt(latest['wind_speed_10m'], 'km/h', 0)} {wind_cardinal(latest['wind_direction_10m'])}")
    row2[1].metric("Couverture nuageuse", fmt(latest["cloud_cover"], "%", 0))
    row2[2].metric("Précipitations (24h)", fmt(precip_24h, "mm"))
    row2[3].metric("Indice AQI (US)", fmt(latest["us_aqi"], decimals=0), aqi_category["label"],
                   delta_color="off")
    row2[4].metric("Score Confort (0-100)", fmt(latest["health_score"]), delta("health_score"))


def render_time_series(df: pd.DataFrame, metrics: List[str], now: pd.Timestamp) -> None:
    """Renders one stacked interactive chart per selected metric, forecasts highlighted."""
    if not metrics:
        st.info("Sélectionnez au moins une métrique.")
        return
    fig = make_subplots(rows=len(metrics), cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        subplot_titles=[label(m) for m in metrics])
    for i, metric in enumerate(metrics, start=1):
        fig.add_trace(go.Scatter(x=df["datetime"], y=df[metric], name=label(metric), mode="lines"), row=i, col=1)
    if df["datetime"].max() > now:
        fig.add_vrect(x0=now, x1=df["datetime"].max(), fillcolor="grey", opacity=0.12, line_width=0,
                      annotation_text="Prévisions", annotation_position="top left")
    fig.update_layout(height=230 * len(metrics) + 60, showlegend=False, hovermode="x unified",
                      margin={"t": 40, "b": 20})
    st.plotly_chart(fig, width="stretch")


def render_air_quality(df: pd.DataFrame, latest: pd.Series) -> None:
    """Renders pollutant time series and current levels compared to WHO thresholds."""
    selected = st.multiselect("Polluants", POLLUTANTS, default=["pm2_5", "pm10", "nitrogen_dioxide", "ozone"],
                              format_func=label)
    if selected:
        long_df = df.melt(id_vars="datetime", value_vars=selected, var_name="polluant", value_name="valeur")
        long_df["polluant"] = long_df["polluant"].map(lambda m: METRICS[m][0])
        fig = px.line(long_df, x="datetime", y="valeur", color="polluant",
                      labels={"valeur": "Concentration (µg/m³)", "datetime": "Date/Heure (UTC)"},
                      title="Évolution des concentrations")
        st.plotly_chart(fig, width="stretch")

    threshold_keys = {"pm2_5": "pm2_5", "pm10": "pm10", "nitrogen_dioxide": "no2",
                      "ozone": "o3", "sulphur_dioxide": "so2"}
    rows = []
    for pollutant, key in threshold_keys.items():
        value = latest[pollutant]
        warning = THRESHOLDS[key]["warning"]
        rows.append({"Polluant": METRICS[pollutant][0], "Actuel (µg/m³)": round(value, 1),
                     "Seuil OMS (µg/m³)": warning, "% du seuil": round(value / warning * 100)})
    ratio_df = pd.DataFrame(rows)
    fig_ratio = px.bar(ratio_df, x="Polluant", y="% du seuil", text="% du seuil",
                       color="% du seuil", color_continuous_scale=["#2e7d32", "#fbc02d", "#c62828"],
                       range_color=[0, 200], title="Niveaux actuels par rapport aux seuils OMS")
    fig_ratio.add_hline(y=100, line_dash="dash", annotation_text="Seuil OMS")
    st.plotly_chart(fig_ratio, width="stretch")
    st.caption(f"CO actuel : {fmt(latest['carbon_monoxide'], 'µg/m³', 0)}")


def render_statistics(df: pd.DataFrame, metrics: List[str]) -> None:
    """Renders aggregated statistics over N hours and 24h / 7 days trends."""
    window_label = st.selectbox("Période d'agrégation", list(STAT_WINDOWS.keys()), index=1)
    hours = STAT_WINDOWS[window_label]
    columns = metrics or ["temperature_2m", "us_aqi"]

    stats = DataProcessor.compute_statistics(df, columns, hours)
    stats.index = [label(m) for m in stats.index]
    st.markdown(f"**Statistiques sur les {window_label}**")
    st.dataframe(stats, width="stretch")

    arrows = {"hausse": "↗️ hausse", "baisse": "↘️ baisse", "stable": "➡️ stable", "indisponible": "-"}
    trend_rows = []
    for metric in columns:
        t24 = DataProcessor.compute_trend(df, metric, 24)
        t7 = DataProcessor.compute_trend(df, metric, 168)
        trend_rows.append({
            "Métrique": label(metric),
            "Tendance 24h": arrows[t24["direction"]], "Variation 24h": t24["variation"],
            "Tendance 7j": arrows[t7["direction"]], "Variation 7j": t7["variation"],
            "Pente 7j (/jour)": t7["slope_per_day"],
        })
    st.markdown("**Tendances d'évolution** (régression linéaire)")
    st.dataframe(pd.DataFrame(trend_rows).set_index("Métrique"), width="stretch")

    st.markdown("**Synthèse journalière**")
    daily = DataProcessor.compute_daily_summary(df).rename(columns={
        "temp_min": "Temp. min (°C)", "temp_max": "Temp. max (°C)", "temp_moyenne": "Temp. moy. (°C)",
        "precipitation_totale": "Précipitations (mm)", "aqi_moyen": "AQI moyen",
    })
    st.dataframe(daily, width="stretch")


def render_map(cities: Dict[str, Dict[str, float]], selected_city: str, mock_mode: bool) -> None:
    """Renders an interactive map of all cities colored by their current AQI category."""
    rows = []
    for name, coords in cities.items():
        city_df = load_city_data(coords["lat"], coords["lon"], mock_mode)
        if city_df.empty:
            continue
        city_latest = DataProcessor.get_latest_observation(city_df)
        category = DataProcessor.get_aqi_category(city_latest["us_aqi"])
        rows.append({
            "Ville": name, "lat": coords["lat"], "lon": coords["lon"],
            "AQI": city_latest["us_aqi"], "Catégorie": category["label"], "color": category["color"],
            "Température (°C)": round(city_latest["temperature_2m"], 1),
            "taille": 22 if name == selected_city else 14,
        })
    map_df = pd.DataFrame(rows)
    color_map = dict(zip(map_df["Catégorie"], map_df["color"]))

    fig_map = px.scatter_map(
        map_df, lat="lat", lon="lon", hover_name="Ville", color="Catégorie", size="taille",
        hover_data={"AQI": ":.0f", "Température (°C)": True, "lat": False, "lon": False, "taille": False},
        color_discrete_map=color_map, zoom=3.5, height=500,
        center={"lat": cities[selected_city]["lat"], "lon": cities[selected_city]["lon"]}
    )
    fig_map.update_layout(map_style="open-street-map", legend_title_text="Qualité de l'air (AQI US)")
    st.plotly_chart(fig_map, width="stretch")
    st.dataframe(map_df[["Ville", "AQI", "Catégorie", "Température (°C)"]].set_index("Ville"), width="stretch")


def render_dashboard():
    """
    Renders Streamlit Web Application Interface.
    Author: Student C (Lead UI/UX)
    """
    st.set_page_config(page_title="Dashboard Météo & AQI", page_icon="🌤️", layout="wide")

    st.title("🌤️ Dashboard Météo & Surveillance Qualité de l'Air")
    st.markdown("Projet 3ᵉ Année Ingénieur — Analyse de données environnementales en temps réel")

    cities = st.session_state.setdefault("cities", dict(DEFAULT_CITIES))
    choices = render_sidebar(cities)
    selected_city = choices["city"]
    city_info = cities[selected_city]

    # Fetch Data
    with st.spinner(f"Chargement des données pour {selected_city}..."):
        df = load_city_data(city_info["lat"], city_info["lon"], choices["mock_mode"])

    if df.empty:
        st.error("Impossible de récupérer ou d'afficher les données.")
        return

    if df.attrs.get("source") == "mock" and not choices["mock_mode"]:
        st.warning("📡 API Open-Meteo injoignable : affichage de données simulées.")

    latest = DataProcessor.get_latest_observation(df)
    now = latest["datetime"]

    # Date and metric filters
    first_day, last_day = df["datetime"].min().date(), df["datetime"].max().date()
    date_range = st.sidebar.date_input("Période affichée", value=(first_day, last_day),
                                       min_value=first_day, max_value=last_day)
    start, end = date_range if len(date_range) == 2 else (date_range[0], last_day)
    filtered = df[(df["datetime"].dt.date >= start) & (df["datetime"].dt.date <= end)]

    metrics = st.sidebar.multiselect(
        "Métriques", [m for m in METRICS if m in df.columns],
        default=["temperature_2m", "apparent_temperature", "relative_humidity_2m", "us_aqi"],
        format_func=label
    )

    # Alert Box Section
    alerts = AlertEngine.detect_alerts(df)
    if alerts:
        for alert in alerts:
            if alert["level"] == "danger":
                st.error(f"🚨 **DANGER** : {alert['message']}")
            else:
                st.warning(f"⚠️ **ATTENTION** : {alert['message']}")
    else:
        st.success("✅ Qualité de l'air et conditions météorologiques stables. Aucune alerte active.")

    # KPI Summary Cards
    st.markdown("---")
    st.caption(f"{selected_city} — dernière mesure : {now:%d/%m/%Y %H:%M} UTC")
    render_kpis(df, latest)

    # Visualizations
    st.markdown("---")
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📈 Évolution Météo", "🏭 Qualité de l'Air", "📊 Statistiques & Tendances", "🗺️ Carte Interactive"]
    )

    with tab1:
        st.subheader("Historique et prévisions (UTC)")
        render_time_series(filtered, metrics, now)

    with tab2:
        render_air_quality(filtered, latest)

    with tab3:
        render_statistics(df, metrics)

    with tab4:
        st.subheader("Qualité de l'air par ville")
        render_map(cities, selected_city, choices["mock_mode"])

    # CSV export
    st.sidebar.markdown("---")
    st.sidebar.download_button(
        "📥 Exporter les données (CSV)",
        filtered.drop(columns=["time"]).to_csv(index=False).encode("utf-8"),
        file_name=f"meteo_{selected_city.split(' ')[0].lower()}_{start}_{end}.csv",
        mime="text/csv",
    )
