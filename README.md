# MeteoPY — Dashboard Météo & Qualité de l'Air

Application Streamlit qui récupère les données météo et de qualité de l'air (API [Open-Meteo](https://open-meteo.com/), sans clé), les met en cache dans SQLite, calcule un score de confort et affiche des alertes basées sur les seuils OMS.

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
