# MeteoPY — Dashboard Météo & Qualité de l'Air

Application Streamlit qui récupère les données météo et de qualité de l'air (API [Open-Meteo](https://open-meteo.com/), sans clé), les met en cache dans SQLite, calcule un score de confort et affiche des alertes basées sur les seuils OMS.

## Fonctionnalités

- **Données** pour 5 villes par défaut + ajout de n'importe quelle ville (géocodage Open-Meteo) :
  température, ressentie, min/max du jour, humidité, pression, vent (vitesse/direction), nuages, précipitations ;
  qualité de l'air : AQI US, PM2.5, PM10, NO2, O3, CO, SO2. Historique de 7 jours + 3 jours de prévisions (UTC).
- **Cache SQLite** (`data/data_cache.db`) avec TTL de 30 min, retries automatiques sur erreurs 429/5xx.
- **Nettoyage** : doublons, valeurs hors bornes physiques, petits trous (≤ 2 h) interpolés.
- **Statistiques** : moyenne, médiane, min, max, écart-type sur 6 h / 24 h / 3 j / 7 j ;
  tendances à 24 h et 7 jours (régression linéaire) ; synthèse journalière.
- **Score de confort** (0-100) combinant température ressentie, humidité, PM2.5 et NO2.
- **Alertes** selon les seuils OMS (PM2.5, PM10, NO2, O3, SO2) et canicule.
- **Interface** : choix de ville, période et métriques, cartes KPI avec variation sur 24 h,
  graphiques interactifs, carte des villes colorée selon l'AQI, export CSV.
- **Mode déconnecté** : données simulées (activable manuellement, automatique si l'API ne répond pas).

## Configuration

Aucune clé API n'est nécessaire. Les paramètres optionnels se règlent dans un fichier `.env`
(voir `.env.example`) : durée du cache, timeout des requêtes, chemin de la base.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement

```bash
streamlit run app.py
```

Le mode « Déconnecté » (barre latérale) utilise des données simulées. Il est aussi activé automatiquement si l'API est injoignable.

## Tests

```bash
pytest
```

## Structure

```
app.py                  # Point d'entrée Streamlit
src/
  config.py             # Villes, seuils OMS, TTL du cache, chemins
  api_client.py         # Requêtes API, cache SQLite (TTL), données mock
  data_processing.py    # Nettoyage pandas, score de confort
  alerts.py             # Moteur d'alertes
  dashboard.py          # Interface Streamlit
tests/                  # Tests pytest
data/                   # Cache SQLite (non versionné)
docs/                   # Cahier des charges et supports
```
