"""Entry point: streamlit run app.py"""
import logging

from src.dashboard import render_dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

render_dashboard()
