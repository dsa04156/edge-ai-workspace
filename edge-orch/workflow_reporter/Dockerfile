FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV STATE_AGGREGATOR_URL=http://state-aggregator:8000/workflow-event

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY workflow_reporter ./workflow_reporter
COPY examples ./examples

CMD ["python", "examples/sample_reporter.py"]
