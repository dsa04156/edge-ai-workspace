# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=builder /install /usr/local
RUN useradd --create-home --uid 10001 telemetry
USER 10001
EXPOSE 8443 8080
ENTRYPOINT ["python", "-m", "telemetry_plane.main"]
