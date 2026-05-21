FROM python:3.12-slim
WORKDIR /app
COPY edge-orch/raw-stream-bridge/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY edge-orch/raw-stream-bridge/raw_stream_bridge /app/raw_stream_bridge
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "raw_stream_bridge.app"]
