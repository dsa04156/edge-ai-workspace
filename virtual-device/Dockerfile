FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY virtual_device ./virtual_device
RUN python -m pip install .

COPY profiles ./profiles

ENTRYPOINT ["python", "-m", "virtual_device.main"]
CMD ["--profile", "profiles/serial-vibration-example.yaml"]
