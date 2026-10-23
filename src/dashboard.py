"""Streamlit user interface (View layer)."""
from dataclasses import dataclass
from html import escape
from typing import Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.alerts import AlertEngine
from src.api_client import WeatherAPIClient
from src.config import AQI_CATEGORIES, DEFAULT_CITIES, METRICS, THRESHOLDS
from src.data_processing import DataProcessor
from src.models import City

# Categorical slots (fixed order) and status colors, validated for both themes
SERIES_COLORS = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
STATUS_COLORS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
MUTED_INK = "#898781"

# Colors follow the pollutant, never its position in the selection
POLLUTANT_SLOTS = {"pm2_5": 0, "pm10": 1, "nitrogen_dioxide": 2, "ozone": 3, "sulphur_dioxide": 4}
WHO_KEYS = {"pm2_5": "pm2_5", "pm10": "pm10", "nitrogen_dioxide": "no2", "ozone": "o3", "sulphur_dioxide": "so2",
            "carbon_monoxide": "co"}
STAT_WINDOWS = {"6 h": 6, "24 h": 24, "3 jours": 72, "7 jours": 168}
WIND_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
SOURCE_LABELS = {"api": ("Données en direct", "green"), "cache": ("Cache local", "blue"),
                 "mock": ("Données simulées", "orange")}
TREND_LABELS = {"hausse": "Hausse", "baisse": "Baisse", "stable": "Stable", "indisponible": "-"}
PLOTLY_CONFIG = {"displayModeBar": False}

CSS = """
<style>
.block-container { padding-top: 2.2rem; max-width: 1400px; }
h1 { letter-spacing: -0.02em; }
.mp-eyebrow { font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.6; }
.mp-card {
    border: 1px solid rgba(127, 127, 127, 0.22); border-radius: 0.75rem;
    padding: 1.25rem 1.4rem; height: 100%; background: rgba(127, 127, 127, 0.04);
}
.mp-hero-value { font-size: 4.2rem; font-weight: 650; line-height: 1; letter-spacing: -0.04em; margin: 0.6rem 0 0.5rem; }
.mp-hero-value span { font-size: 1.6rem; font-weight: 500; opacity: 0.6; margin-left: 0.2rem; vertical-align: top; }
.mp-hero-sub { font-size: 0.95rem; opacity: 0.75; }
.mp-hero-cond { font-size: 1.1rem; font-weight: 600; margin-top: 0.9rem; }
.mp-aqi-value { font-size: 3rem; font-weight: 650; line-height: 1; letter-spacing: -0.03em; margin: 0.6rem 0 0.35rem; }
.mp-aqi-label { display: flex; align-items: center; gap: 0.5rem; font-weight: 600; }
.mp-dot { width: 0.7rem; height: 0.7rem; border-radius: 50%; display: inline-block; }
.mp-gauge { position: relative; display: flex; gap: 2px; margin-top: 1.1rem; height: 0.45rem; }
.mp-gauge div { flex: 1; border-radius: 2px; opacity: 0.85; }
.mp-gauge-marker {
    position: absolute; top: -0.3rem; width: 3px; height: 1.05rem; border-radius: 2px;
    background: currentColor; transform: translateX(-50%);
}
.mp-gauge-scale { display: flex; justify-content: space-between; font-size: 0.72rem; opacity: 0.55; margin-top: 0.35rem; }
.mp-alert {
    display: flex; gap: 0.9rem; align-items: baseline; padding: 0.7rem 1rem; margin-bottom: 0.5rem;
    border-radius: 0.6rem; border: 1px solid rgba(127, 127, 127, 0.22); border-left-width: 4px;
}
.mp-alert-title { font-size: 0.93rem; font-weight: 600; }
.mp-alert-msg { font-size: 0.93rem; opacity: 0.75; }
</style>
"""


def theme_type() -> str:
    """Returns the active Streamlit theme ("light" or "dark")."""
    try:
        return st.context.theme.type or "light"
    except AttributeError:
        return "light"


def series_color(slot: int) -> str:
    """Returns the categorical color of a slot for the active theme."""
    return SERIES_COLORS[theme_type()][slot]


def label(metric: str) -> str:
    """Returns the display label of a metric with its unit."""
    name, unit = METRICS.get(metric, (metric, ""))
    return f"{name} ({unit})" if unit else name


def wind_cardinal(degrees: float) -> str:
    """Converts a wind direction in degrees to a cardinal point."""
    if pd.isna(degrees):
        return "-"
    return WIND_DIRECTIONS[int((degrees % 360) / 45 + 0.5) % 8]


def describe_sky(cloud_cover: float, precipitation: float) -> str:
    """Short textual description of the sky from cloud cover and precipitation."""
    if pd.notna(precipitation) and precipitation >= 0.1:
        return "Pluie"
    if pd.isna(cloud_cover):
        return "Conditions inconnues"
    if cloud_cover < 20:
        return "Ciel dégagé"
    if cloud_cover < 60:
        return "Partiellement nuageux"
    if cloud_cover < 90:
        return "Nuageux"
    return "Couvert"


def fmt(value: float, unit: str = "", decimals: int = 1) -> str:
    """Formats a numeric value, returning N/A for missing data."""
    if pd.isna(value):
        return "N/A"
    return f"{value:.{decimals}f} {unit}".strip()


def style_figure(fig: go.Figure, height: int, legend: bool = False) -> go.Figure:
    """Applies the common minimal layout to a Plotly figure."""
    fig.update_layout(
        height=height, margin={"l": 8, "r": 8, "t": 36 if legend else 16, "b": 8},
        hovermode="x unified", showlegend=legend,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "title": None},
        font={"family": "Inter, system-ui, sans-serif"},
    )
    fig.update_xaxes(title=None, showgrid=False)
    fig.update_yaxes(title=None)
    return fig


@dataclass(frozen=True)
class SidebarChoices:
    """User choices made in the selection panel."""
    city: City
    mock_mode: bool


def load_city_data(city: City, mock_mode: bool) -> pd.DataFrame:
    """
    Fetches, processes and enriches the data of one location (API calls are cached in SQLite).
    The data source ("api", "cache" or "mock") is stored in df.attrs["source"].
    """
    raw_data = WeatherAPIClient().fetch_weather_and_air_quality(city.lat, city.lon, mock_mode=mock_mode)
    df = DataProcessor.process_raw_api_data(raw_data)
    if not df.empty:
        df["health_score"] = DataProcessor.calculate_custom_health_index(df)
    df.attrs["source"] = raw_data.get("source", "api")
    return df


def render_sidebar(cities: Dict[str, City]) -> SidebarChoices:
    """Renders the selection panel and returns the user choices."""
    with st.sidebar:
        st.markdown("### MeteoPY")
        st.caption("Surveillance météo et qualité de l'air")

        selected_city = st.selectbox("Ville", list(cities.keys()))
        with st.form("add_city", clear_on_submit=True, border=False):
            new_city = st.text_input("Ajouter une ville", placeholder="Rechercher, ex. Bordeaux")
            if st.form_submit_button("Ajouter", width="stretch") and new_city:
                found = WeatherAPIClient().geocode_city(new_city)
                if found:
                    cities[found.label] = found
                    st.rerun()
                else:
                    st.error(f"Ville « {new_city} » introuvable.")

        mock_mode = st.toggle("Mode déconnecté", value=False, help="Utilise des données simulées.")
    return SidebarChoices(cities[selected_city], mock_mode)


def render_header(city: str, latest: pd.Series, source: str, mock_mode: bool) -> None:
    """Renders the page title, last update time and data source."""
    st.markdown('<div class="mp-eyebrow">Tableau de bord</div>', unsafe_allow_html=True)
    st.title(city, anchor=False)
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.caption(f"Dernière mesure le {latest['datetime']:%d/%m/%Y à %H:%M} UTC", width="content")
        source_label, color = SOURCE_LABELS.get(source, SOURCE_LABELS["api"])
        st.badge(source_label, color=color)
    if source == "mock" and not mock_mode:
        render_notice("info", "API Open-Meteo injoignable : les valeurs affichées sont simulées.")


def render_notice(level: str, message: str) -> None:
    """
    Renders one alert line with a colored rule. The title text carries the level
    ("Alerte ...", "Vigilance ..."), so the meaning never relies on color alone.
    """
    colors = {"danger": STATUS_COLORS["critical"], "warning": STATUS_COLORS["warning"],
              "good": STATUS_COLORS["good"], "info": MUTED_INK}
    title, _, detail = message.partition(" : ")
    st.markdown(
        f'<div class="mp-alert" style="border-left-color:{colors[level]}">'
        f'<span class="mp-alert-title">{escape(title)}</span>'
        f'<span class="mp-alert-msg">{escape(detail)}</span></div>',
        unsafe_allow_html=True,
    )


def render_alerts(df: pd.DataFrame) -> None:
    """Renders the active alerts, or a single line when everything is within thresholds."""
    alerts = AlertEngine.detect_alerts(df)
    if not alerts:
        render_notice("good", "Aucune alerte : pas de dépassement des seuils OMS ni de forte chaleur.")
    for alert in alerts:
        render_notice(alert.level, alert.message)


def render_current_conditions(df: pd.DataFrame, latest: pd.Series) -> None:
    """Renders the hero temperature card and the AQI card with its category gauge."""
    today = DataProcessor.compute_daily_summary(df[df["datetime"].dt.date == latest["datetime"].date()])
    precip_24h = DataProcessor.get_window(df, 24)["precipitation"].sum(min_count=1)
    t_min = today["temp_min"].iloc[0] if not today.empty else float("nan")
    t_max = today["temp_max"].iloc[0] if not today.empty else float("nan")

    hero = (
        '<div class="mp-card">'
        '<div class="mp-eyebrow">Conditions actuelles</div>'
        f'<div class="mp-hero-value">{fmt(latest["temperature_2m"], decimals=1)}<span>°C</span></div>'
        f'<div class="mp-hero-sub">Ressenti {fmt(latest["apparent_temperature"], "°C")}'
        f' &nbsp;·&nbsp; Min {fmt(t_min, "°C")} &nbsp;·&nbsp; Max {fmt(t_max, "°C")}</div>'
        f'<div class="mp-hero-cond">{describe_sky(latest["cloud_cover"], latest["precipitation"])}</div>'
        f'<div class="mp-hero-sub">Vent {fmt(latest["wind_speed_10m"], "km/h", 0)} '
        f'{wind_cardinal(latest["wind_direction_10m"])} &nbsp;·&nbsp; Pluie 24 h {fmt(precip_24h, "mm")}</div>'
        '</div>'
    )

    aqi = latest["us_aqi"]
    category = DataProcessor.get_aqi_category(aqi)
    scale_max = 300
    segments = "".join(
        f'<div style="background:{color}; flex:{(min(upper, scale_max) - lower) / scale_max}"></div>'
        for (upper, _, color), lower in zip(AQI_CATEGORIES, [0] + [c[0] for c in AQI_CATEGORIES[:-1]])
        if lower < scale_max
    )
    marker = "" if pd.isna(aqi) else (
        f'<div class="mp-gauge-marker" style="left:{min(aqi, scale_max) / scale_max * 100:.1f}%"></div>'
    )
    aqi_card = (
        '<div class="mp-card">'
        '<div class="mp-eyebrow">Qualité de l\'air · AQI US</div>'
        f'<div class="mp-aqi-value">{fmt(aqi, decimals=0)}</div>'
        f'<div class="mp-aqi-label"><span class="mp-dot" style="background:{category["color"]}"></span>'
        f'{category["label"]}</div>'
        f'<div class="mp-gauge">{segments}{marker}</div>'
        '<div class="mp-gauge-scale"><span>0</span><span>100</span><span>200</span><span>300+</span></div>'
        f'<div class="mp-hero-sub" style="margin-top:0.9rem">Score confort {fmt(latest["health_score"])} / 100</div>'
        '</div>'
    )

    left, right = st.columns([1.35, 1], gap="medium")
    left.markdown(hero, unsafe_allow_html=True)
    right.markdown(aqi_card, unsafe_allow_html=True)


def render_kpis(df: pd.DataFrame, latest: pd.Series) -> None:
    """Renders the KPI cards with their 24 h variation and a 24 h sparkline."""
    last_24h = DataProcessor.get_window(df, 24)
    kpis = [
        ("relative_humidity_2m", 0, "off"), ("surface_pressure", 0, "off"),
        ("wind_speed_10m", 0, "off"), ("cloud_cover", 0, "off"),
        ("pm2_5", 1, "inverse"), ("nitrogen_dioxide", 1, "inverse"),
        ("ozone", 1, "inverse"), ("health_score", 1, "normal"),
    ]
    for row_start in (0, 4):
        cols = st.columns(4, gap="small")
        for col, (metric, decimals, delta_color) in zip(cols, kpis[row_start:row_start + 4]):
            name, unit = METRICS[metric]
            variation = DataProcessor.compute_variation(df, metric, 24)
            col.metric(
                name, fmt(latest[metric], unit, decimals),
                None if pd.isna(variation) else f"{variation:+.{decimals}f} en 24 h",
                delta_color=delta_color, border=True,
                chart_data=last_24h[metric].dropna().round(2).tolist(), chart_type="area",
            )


def render_evolution(df: pd.DataFrame, now: pd.Timestamp) -> None:
    """Renders one small chart per selected metric (shared time axis), forecasts shaded."""
    options = [m for m in METRICS if m in df.columns and m != "wind_direction_10m"]
    metrics = st.pills("Métriques", options, selection_mode="multi",
                       default=["temperature_2m", "relative_humidity_2m", "precipitation"],
                       format_func=lambda m: METRICS[m][0])
    if not metrics:
        st.info("Sélectionnez au moins une métrique.")
        return

    fig = make_subplots(rows=len(metrics), cols=1, shared_xaxes=True, vertical_spacing=0.07,
                        subplot_titles=[label(m) for m in metrics])
    for i, metric in enumerate(metrics, start=1):
        if metric == "precipitation":
            trace = go.Bar(x=df["datetime"], y=df[metric], name=label(metric), marker_color=series_color(0))
        else:
            trace = go.Scatter(x=df["datetime"], y=df[metric], name=label(metric), mode="lines",
                               line={"width": 2, "color": series_color(0)})
        fig.add_trace(trace, row=i, col=1)
    fig.update_annotations(font_size=12, xanchor="left", x=0)
    if df["datetime"].max() > now:
        fig.add_vrect(x0=now, x1=df["datetime"].max(), fillcolor=MUTED_INK, opacity=0.1, line_width=0)
        fig.add_annotation(x=now, y=1.0, xref="x", yref="paper", text="Prévisions", showarrow=False,
                           xanchor="left", yanchor="bottom", font={"size": 11, "color": MUTED_INK})
    st.plotly_chart(style_figure(fig, 190 * len(metrics) + 40), width="stretch", config=PLOTLY_CONFIG)

    st.markdown("##### Températures journalières")
    daily = DataProcessor.compute_daily_summary(df).reset_index()
    fig_daily = go.Figure(go.Bar(
        x=daily["date"], y=daily["temp_max"] - daily["temp_min"], base=daily["temp_min"],
        marker={"color": series_color(0), "cornerradius": 4},
        customdata=daily[["temp_min", "temp_max"]],
        hovertemplate="Min %{customdata[0]:.1f} °C<br>Max %{customdata[1]:.1f} °C<extra></extra>",
    ))
    fig_daily.update_yaxes(ticksuffix=" °C", range=[daily["temp_min"].min() - 2, daily["temp_max"].max() + 2])
    fig_daily.update_layout(bargap=0.45)
    st.plotly_chart(style_figure(fig_daily, 280), width="stretch", config=PLOTLY_CONFIG)


def render_air_quality(df: pd.DataFrame, latest: pd.Series) -> None:
    """Renders pollutant time series and current levels compared to WHO guidelines."""
    left, right = st.columns([1.6, 1], gap="large")

    with left:
        st.markdown("##### Concentrations (µg/m³)")
        selected = st.pills("Polluants", list(POLLUTANT_SLOTS), selection_mode="multi",
                            default=["pm2_5", "pm10", "nitrogen_dioxide"],
                            format_func=lambda m: METRICS[m][0], label_visibility="collapsed")
        fig = go.Figure()
        for pollutant in selected or []:
            fig.add_trace(go.Scatter(
                x=df["datetime"], y=df[pollutant], name=METRICS[pollutant][0], mode="lines",
                line={"width": 2, "color": series_color(POLLUTANT_SLOTS[pollutant])},
            ))
        st.plotly_chart(style_figure(fig, 380, legend=True), width="stretch", config=PLOTLY_CONFIG)
        st.caption(f"Monoxyde de carbone (CO) actuel : {fmt(latest['carbon_monoxide'], 'µg/m³', 0)}")

    with right:
        st.markdown("##### Moyenne / valeur guide OMS")
        rows = []
        for pollutant, key in WHO_KEYS.items():
            threshold = THRESHOLDS[key]
            mean = DataProcessor.rolling_mean(df, pollutant, threshold["hours"], end=latest["datetime"])
            if pd.isna(mean):
                continue
            ratio = mean / threshold["warning"] * 100
            status = "good" if ratio < 100 else "serious" if ratio < 200 else "critical"
            rows.append({"Polluant": f"{METRICS[pollutant][0]} ({threshold['hours']} h)", "ratio": ratio,
                         "color": STATUS_COLORS[status], "text": f"{ratio:.0f} %", "value": mean,
                         "threshold": threshold["warning"]})
        if not rows:
            st.info("Pas assez de mesures sur la période pour calculer les moyennes.")
            return
        ratio_df = pd.DataFrame(rows).iloc[::-1]
        fig_ratio = go.Figure(go.Bar(
            x=ratio_df["ratio"], y=ratio_df["Polluant"], orientation="h", text=ratio_df["text"],
            textposition="outside", cliponaxis=False,
            marker={"color": ratio_df["color"], "cornerradius": 4},
            customdata=ratio_df[["value", "threshold"]],
            hovertemplate="%{y} : %{customdata[0]:.1f} µg/m³ (seuil %{customdata[1]} µg/m³)<extra></extra>",
        ))
        fig_ratio.add_vline(x=100, line_dash="dot", line_color=MUTED_INK)
        fig_ratio.add_annotation(x=100, y=1, xref="x", yref="paper", text="Seuil OMS", showarrow=False,
                                 yanchor="bottom", font={"size": 11, "color": MUTED_INK})
        fig_ratio.update_xaxes(ticksuffix=" %", range=[0, max(220, ratio_df["ratio"].max() * 1.2)])
        style_figure(fig_ratio, 380).update_layout(hovermode="closest", margin={"t": 28})
        st.plotly_chart(fig_ratio, width="stretch", config=PLOTLY_CONFIG)


def render_statistics(df: pd.DataFrame) -> None:
    """Renders aggregated statistics over N hours, 24 h / 7 days trends and a daily summary."""
    columns = ["temperature_2m", "apparent_temperature", "relative_humidity_2m", "surface_pressure",
               "wind_speed_10m", "pm2_5", "pm10", "nitrogen_dioxide", "ozone", "us_aqi", "health_score"]
    window_label = st.segmented_control("Période", list(STAT_WINDOWS), default="24 h", required=True)
    hours = STAT_WINDOWS[window_label]

    number = st.column_config.NumberColumn(format="%.1f")
    stats = DataProcessor.compute_statistics(df, columns, hours)
    stats.index = [label(m) for m in stats.index]
    st.markdown(f"##### Statistiques sur {window_label}")
    st.dataframe(stats, width="stretch", height="content", column_config={c: number for c in stats.columns})

    trend_rows = []
    for metric in columns:
        t24 = DataProcessor.compute_trend(df, metric, 24)
        t7 = DataProcessor.compute_trend(df, metric, 168)
        trend_rows.append({
            "Métrique": label(metric),
            "Tendance 24 h": TREND_LABELS[t24["direction"]], "Variation 24 h": t24["variation"],
            "Tendance 7 j": TREND_LABELS[t7["direction"]], "Variation 7 j": t7["variation"],
            "Pente 7 j (/jour)": t7["slope_per_day"],
        })
    st.markdown("##### Tendances (régression linéaire)")
    st.dataframe(
        pd.DataFrame(trend_rows).set_index("Métrique"), width="stretch", height="content",
        column_config={c: st.column_config.NumberColumn(format="%+.2f")
                       for c in ("Variation 24 h", "Variation 7 j", "Pente 7 j (/jour)")},
    )

    st.markdown("##### Synthèse journalière")
    daily = DataProcessor.compute_daily_summary(df).rename(columns={
        "temp_min": "Temp. min (°C)", "temp_max": "Temp. max (°C)", "temp_moyenne": "Temp. moy. (°C)",
        "precipitation_totale": "Précipitations (mm)", "aqi_moyen": "AQI moyen",
    })
    st.dataframe(daily, width="stretch", height="content", column_config={c: number for c in daily.columns})


def render_map(cities: Dict[str, City], selected_city: City, mock_mode: bool) -> None:
    """Renders an interactive map of all cities colored by their current AQI category."""
    rows = []
    for name, city in cities.items():
        city_df = load_city_data(city, mock_mode)
        if city_df.empty:
            continue
        city_latest = DataProcessor.get_latest_observation(city_df)
        category = DataProcessor.get_aqi_category(city_latest["us_aqi"])
        rows.append({
            "Ville": name, "lat": city.lat, "lon": city.lon,
            "AQI": city_latest["us_aqi"], "Catégorie": category["label"], "color": category["color"],
            "Température (°C)": round(city_latest["temperature_2m"], 1),
            "taille": 20 if city == selected_city else 12,
        })
    map_df = pd.DataFrame(rows)

    left, right = st.columns([1.5, 1], gap="large")
    with left:
        fig_map = px.scatter_map(
            map_df, lat="lat", lon="lon", hover_name="Ville", color="Catégorie", size="taille", size_max=20,
            hover_data={"AQI": ":.0f", "Température (°C)": True, "lat": False, "lon": False, "taille": False},
            color_discrete_map=dict(zip(map_df["Catégorie"], map_df["color"])), zoom=3.6, height=480,
            center={"lat": selected_city.lat, "lon": selected_city.lon},
            map_style="carto-darkmatter" if theme_type() == "dark" else "carto-positron",
        )
        fig_map.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0},
                              legend={"orientation": "h", "y": 0.01, "x": 0.01, "title": None,
                                      "bgcolor": "rgba(127,127,127,0.15)"})
        st.plotly_chart(fig_map, width="stretch", config=PLOTLY_CONFIG)
    with right:
        table = map_df.sort_values("AQI")[["Ville", "AQI", "Catégorie", "Température (°C)"]]
        st.dataframe(
            table, hide_index=True, width="stretch", height="content",
            column_config={
                "AQI": st.column_config.ProgressColumn("AQI", format="%.0f", min_value=0, max_value=300,
                                                       width="small"),
                "Température (°C)": st.column_config.NumberColumn("Temp.", format="%.1f °C"),
            },
        )


def render_dashboard():
    """
    Renders Streamlit Web Application Interface.
    Author: Student C (Lead UI/UX)
    """
    st.set_page_config(page_title="MeteoPY · Météo & Qualité de l'air", page_icon=":material/air:",
                       layout="wide")
    st.html(CSS)

    cities = st.session_state.setdefault("cities", {city.label: city for city in DEFAULT_CITIES})
    choices = render_sidebar(cities)
    selected_city = choices.city

    with st.spinner(f"Chargement des données pour {selected_city.name}..."):
        df = load_city_data(selected_city, choices.mock_mode)

    if df.empty:
        st.error("Impossible de récupérer ou d'afficher les données.")
        return

    latest = DataProcessor.get_latest_observation(df)
    now = latest["datetime"]

    # Date filter and export (sidebar)
    first_day, last_day = df["datetime"].min().date(), df["datetime"].max().date()
    with st.sidebar:
        date_range = st.date_input("Période affichée", value=(first_day, last_day),
                                   min_value=first_day, max_value=last_day, format="DD/MM/YYYY")
    start, end = date_range if len(date_range) == 2 else (date_range[0], last_day)
    filtered = df[(df["datetime"].dt.date >= start) & (df["datetime"].dt.date <= end)]

    with st.sidebar:
        st.divider()
        st.download_button(
            "Exporter en CSV", filtered.drop(columns=["time"]).to_csv(index=False).encode("utf-8"),
            file_name=f"meteo_{selected_city.name.lower()}_{start}_{end}.csv",
            mime="text/csv", width="stretch",
        )
        st.caption("Données Open-Meteo · Seuils OMS 2021 · Heures en UTC")

    render_header(selected_city.label, latest, df.attrs.get("source", "api"), choices.mock_mode)
    render_alerts(df)
    st.write("")
    render_current_conditions(df, latest)
    st.write("")
    render_kpis(df, latest)
    st.write("")

    tab_evolution, tab_air, tab_stats, tab_map = st.tabs(["Évolution", "Qualité de l'air", "Statistiques", "Carte"])
    with tab_evolution:
        render_evolution(filtered, now)
    with tab_air:
        render_air_quality(filtered, latest)
    with tab_stats:
        render_statistics(df)
    with tab_map:
        render_map(cities, selected_city, choices.mock_mode)
