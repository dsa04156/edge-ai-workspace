FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV STATE_AGGREGATOR_URL=http://state-aggregator:8000

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY placement_engine ./placement_engine

EXPOSE 8001

CMD ["uvicorn", "placement_engine.main:app", "--host", "0.0.0.0", "--port", "8001"]
