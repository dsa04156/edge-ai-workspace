FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vd_runtime/ vd_runtime/
COPY models/ models/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM
CMD ["python", "-m", "vd_runtime"]
