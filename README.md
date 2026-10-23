# MeteoPY — Dashboard Météo & Qualité de l'Air

[![CI](https://github.com/6idm/MeteoPY/actions/workflows/ci.yml/badge.svg)](https://github.com/6idm/MeteoPY/actions/workflows/ci.yml)

Application Streamlit qui récupère les données météo et de qualité de l'air de plusieurs villes
(API [Open-Meteo](https://open-meteo.com/), sans clé), les met en cache dans SQLite, les nettoie et les analyse
avec pandas, calcule un score de confort et déclenche des alertes selon les lignes directrices de l'OMS.

Projet réalisé par **Etienne**, **Rostom** et **Sid'ahmed** (3e année cycle ingénieur, EPSI).
Le cahier des charges est dans [`docs/`](docs/).

## Sommaire

1. [Démarrage rapide](#démarrage-rapide)
2. [Docker](#docker)
3. [Fonctionnalités](#fonctionnalités)
4. [Architecture](#architecture)
5. [Explications techniques](#explications-techniques)
6. [Configuration](#configuration)
7. [Tests et qualité](#tests-et-qualité)

## Démarrage rapide

Prérequis : Python 3.11 ou plus récent.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # dépendances + pytest + ruff
streamlit run app.py
```

Le dashboard s'ouvre sur http://localhost:8501. Sans connexion internet, activez « Mode déconnecté »
dans la barre latérale ; ce mode s'active aussi tout seul si l'API ne répond pas.

## Docker

```bash
docker compose up --build -d     # construit l'image et démarre le dashboard
docker compose logs -f           # suivre les logs
docker compose down              # arrêter (ajouter -v pour supprimer le cache)
```

Le dashboard est accessible sur http://localhost:8501. Le cache SQLite est conservé dans le volume
`meteo-cache`, et le fichier `.env` est pris en compte s'il existe.

## Fonctionnalités

| Besoin du cahier des charges | Réalisation |
|---|---|
| Au moins 5 villes | Paris, Lyon, Marseille, Londres, Madrid, et ajout de n'importe quelle ville par géocodage |
| Données météo | Température, ressentie, min/max du jour, humidité, pression, vent (vitesse/direction), nuages, précipitations |
| Qualité de l'air | AQI US, PM2.5, PM10, NO2, O3, CO, SO2 |
| Cache avec durée de validité | SQLite (`data/data_cache.db`), expiration après 30 min |
| Statistiques | Moyenne, médiane, min, max, écart-type sur 6 h / 24 h / 3 j / 7 j ; synthèse par jour |
| Tendances | Régression linéaire sur 24 h et 7 jours |
| Score de confort | Note de 0 à 100 (ressentie, humidité, PM2.5, NO2) |
| Alertes | Seuils OMS 2021 sur moyennes glissantes, canicule selon la méthode de Météo-France |
| Interface | Choix de la ville, de la période et des métriques ; cartes KPI ; graphiques Plotly ; carte colorée selon l'AQI |
| Bonus | Export CSV, mode déconnecté, conteneur Docker |

## Architecture

```
app.py                  # Point d'entrée : streamlit run app.py
src/
  config.py             # Villes, variables API, seuils OMS et canicule, paramètres du cache
  models.py             # Dataclasses City et Alert
  api_client.py         # Appels HTTP, cache SQLite, géocodage, données simulées
  data_processing.py    # Nettoyage pandas, statistiques, tendances, score de confort
  alerts.py             # Moteur de règles d'alerte
  dashboard.py          # Interface Streamlit
tests/                  # Tests pytest (API, traitement, alertes)
data/                   # Cache SQLite (non versionné)
docs/                   # Cahier des charges et supports de cours
.github/workflows/      # Intégration continue (ruff + pytest)
.streamlit/config.toml  # Thème clair / sombre
Dockerfile, docker-compose.yml
```

Les couches sont séparées selon un découpage de type MVC :

```
Open-Meteo (météo, air, géocodage)
        │  JSON
        ▼
WeatherAPIClient ──── cache SQLite (TTL 30 min)
        │  dict brut  (repli : données simulées)
        ▼
DataProcessor ─────── DataFrame horaire nettoyé + score de confort
        │
        ├──► AlertEngine ──► list[Alert]
        ▼
dashboard.py (vue Streamlit)
```

Le client API ne connaît ni pandas ni Streamlit, et le traitement ne connaît pas l'interface.
On peut donc tester chaque couche séparément.

## Explications techniques

### Récupération et cache

Pour chaque ville, deux requêtes sont envoyées : l'API météo et l'API qualité de l'air d'Open-Meteo. Les données
sont horaires, en UTC, et couvrent 7 jours d'historique et 3 jours de prévision. La réponse combinée est
enregistrée dans la table SQLite `api_cache` (clé = coordonnées, réponse JSON, horodatage). Tant que
l'entrée a moins de 30 minutes, elle est relue au lieu d'appeler l'API.

Gestion des erreurs :
- les erreurs 429 et 5xx sont réessayées deux fois, avec un délai qui double à chaque essai ;
- une erreur réseau (`requests.exceptions.RequestException`) ou un JSON invalide bascule sur les données
  simulées, et un bandeau prévient l'utilisateur ;
- une ville introuvable ou un résultat de géocodage incomplet renvoie `None`, et un message s'affiche.

La source des données (`api`, `cache` ou `mock`) apparaît sous forme de badge dans l'en-tête.

### Nettoyage

`DataProcessor.clean_data` :
1. supprime les horodatages en double ;
2. convertit les valeurs en nombres (une valeur illisible devient `NaN`) ;
3. supprime les valeurs physiquement impossibles (humidité hors de 0 à 100 %, concentrations négatives, AQI > 500…) ;
4. comble par interpolation linéaire les trous de 2 h au plus, entre deux mesures ;
5. marque les lignes de prévision (`is_forecast`).

### Statistiques et tendances

- Les statistiques portent sur la fenêtre des N dernières heures, jusqu'à la dernière observation ; les prévisions
  sont exclues.
- La tendance est la pente d'une régression linéaire par moindres carrés (`numpy.polyfit`). On l'exprime
  comme une variation sur la fenêtre. Elle est jugée « stable » si cette variation est inférieure à 5 % de la moyenne.

### Score de confort

```
score = 100 − ( 1,5 × |T_ressentie − 21|
              + 0,3 × |humidité − 50|
              + 12  × PM2.5 / 15
              +  6  × NO2 / 25 )          borné entre 0 et 100
```

21 °C et 50 % d'humidité sont considérés comme idéaux. Les polluants sont rapportés à leur valeur guide OMS.
Exemple : 25 °C ressentis, 60 % d'humidité, 10 µg/m³ de PM2.5 et 20 µg/m³ de NO2 donnent
100 − (6 + 3 + 8 + 4,8) = **78,2**.

### Alertes

Les lignes directrices de l'OMS (2021) portent sur des **concentrations moyennes**, pas sur des valeurs horaires.
Le moteur compare donc la moyenne glissante sur la période de référence, calculée jusqu'à la dernière
observation :

| Polluant | Période | Vigilance (valeur guide OMS) | Alerte (objectif intermédiaire OMS) |
|---|---|---|---|
| PM2.5 | 24 h | 15 µg/m³ | 25 µg/m³ (IT-4) |
| PM10 | 24 h | 45 µg/m³ | 50 µg/m³ (IT-4) |
| NO2 | 24 h | 25 µg/m³ | 50 µg/m³ (IT-2) |
| O3 | 8 h | 100 µg/m³ | 120 µg/m³ (IT-2) |
| SO2 | 24 h | 40 µg/m³ | 50 µg/m³ (IT-2) |
| CO | 24 h | 4 mg/m³ | 7 mg/m³ (IT-1) |

Une moyenne n'est calculée que si au moins 75 % des valeurs horaires sont disponibles (18 h sur 24), comme
le prévoit la réglementation européenne.

**Canicule** (méthode de Météo-France) : on calcule la moyenne des températures minimales et maximales
sur 3 jours (aujourd'hui et les 2 jours de prévision).
- *Alerte Canicule* : les deux moyennes atteignent leur seuil (20 °C la nuit, 33 °C le jour).
- *Vigilance Forte Chaleur* : au moins un des 3 jours atteint 33 °C, sans que la canicule soit avérée.

Météo-France fixe ces seuils département par département. Les valeurs retenues sont typiques et se modifient
dans `HEATWAVE` (`src/config.py`).

Sources : [WHO global air quality guidelines (2021)](https://www.who.int/publications/i/item/9789240034228),
[Météo-France, vigilance canicule](https://meteofrance.com/comprendre-la-meteo/temperatures/la-canicule).

### Mode déconnecté

`WeatherAPIClient._generate_mock_data` produit des données au même format que l'API : un cycle de température
sur la journée, une humidité qui varie en sens inverse, et des polluants tirés au hasard. Le générateur est
initialisé avec les coordonnées et l'heure courante, donc les valeurs ne changent pas d'un rafraîchissement
de page à l'autre.

### Exemple d'utilisation des modules

```python
from src.alerts import AlertEngine
from src.api_client import WeatherAPIClient
from src.data_processing import DataProcessor

client = WeatherAPIClient()
city = client.geocode_city("Bordeaux")           # City(name='Bordeaux', lat=44.84, lon=-0.58, country='France')
raw = client.fetch_weather_and_air_quality(city.lat, city.lon)
df = DataProcessor.process_raw_api_data(raw)

DataProcessor.compute_statistics(df, ["temperature_2m", "pm2_5"], hours=24)
DataProcessor.compute_trend(df, "temperature_2m", hours=168)  # {'variation': ..., 'direction': 'hausse'}
for alert in AlertEngine.detect_alerts(df):
    print(alert.level, alert.message)
```

## Configuration

Aucune clé API n'est nécessaire. Les paramètres facultatifs se placent dans un fichier `.env` à la racine
(voir `.env.example`, le fichier `.env` n'est pas versionné) :

| Variable | Défaut | Rôle |
|---|---|---|
| `METEO_CACHE_TTL_MINUTES` | `30` | Durée de validité du cache |
| `METEO_REQUEST_TIMEOUT_SECONDS` | `5` | Délai maximal d'une requête HTTP |
| `METEO_CACHE_DB` | `data/data_cache.db` | Chemin de la base SQLite |

## Tests et qualité

```bash
pytest          # tests unitaires
ruff check .    # linter (style, imports, erreurs courantes)
```

Les tests n'appellent pas le réseau : les réponses HTTP sont simulées avec `monkeypatch`, et le cache utilise
une base temporaire. Ils couvrent le cache et son expiration, le repli en cas d'erreur réseau ou de JSON
corrompu, le géocodage, le nettoyage, les statistiques, les tendances, le score de confort, et chaque type
d'alerte (moyennes 24 h et 8 h, couverture insuffisante, canicule ou simple pic de chaleur).

La CI GitHub Actions (`.github/workflows/ci.yml`) lance `ruff check` puis `pytest` sous Python 3.11 et 3.13
à chaque push sur `main` et à chaque pull request.

