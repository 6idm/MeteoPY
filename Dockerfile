FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Dependencies first to benefit from Docker layer caching
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .
COPY src/ src/
COPY .streamlit/ .streamlit/

# Non-root user owning the SQLite cache directory
RUN useradd --create-home appuser && mkdir -p data && chown appuser:appuser data
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
