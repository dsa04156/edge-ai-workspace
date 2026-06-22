FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system app && adduser --system --ingroup app app

COPY --chown=app:app vision_stage_runner ./vision_stage_runner

USER app
EXPOSE 8080

CMD ["uvicorn", "vision_stage_runner.service:app", "--host", "0.0.0.0", "--port", "8080"]
