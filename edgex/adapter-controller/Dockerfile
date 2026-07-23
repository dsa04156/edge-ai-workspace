FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ADAPTER_RUNTIME_CATALOG_PATH=/app/config/runtime_templates.json

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup --system --gid 2001 controller \
    && adduser --system --uid 2001 --ingroup controller controller

COPY --chown=2001:2001 app ./app
COPY --chown=2001:2001 config ./config

USER 2001:2001

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
