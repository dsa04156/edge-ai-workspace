FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLACEMENT_ENGINE_URL=http://placement-engine:8001
ENV STATE_AGGREGATOR_URL=http://state-aggregator:8000/workflow-event
ENV EXECUTOR_NAMESPACE=default

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY workflow_executor ./workflow_executor

EXPOSE 8002

CMD ["uvicorn", "workflow_executor.main:app", "--host", "0.0.0.0", "--port", "8002"]
