FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY vision_stage_runner ./vision_stage_runner

CMD ["python", "-m", "vision_stage_runner.main", "--stage", "capture"]
