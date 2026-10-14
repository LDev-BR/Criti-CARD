FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt requirements-production.txt ./
RUN pip install --no-cache-dir -r requirements-production.txt \
    && groupadd --gid 10001 criticard \
    && useradd --uid 10001 --gid criticard --no-create-home criticard

COPY --chown=10001:10001 . .
RUN mkdir -p /app/static/uploads /app/static/cards /app/instance/outbox \
    && chown -R 10001:10001 /app/static/uploads /app/static/cards /app/instance

USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--worker-class", "gthread", "--workers", "1", "--threads", "32", "--bind", "0.0.0.0:8000", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
