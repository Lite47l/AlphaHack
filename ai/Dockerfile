# AI-сервис (FastAPI). Контекст сборки — каталог ai/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    STATE_DIR=/state

WORKDIR /srv

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /srv --shell /usr/sbin/nologin app \
    && mkdir -p /state /data \
    && chown app:app /state

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
