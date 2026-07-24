FROM python:3.11-alpine

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN addgroup -S -g 2002 discovery \
    && adduser -S -D -H -u 2002 -G discovery discovery

COPY --chown=2002:2002 app ./app

USER 2002:2002

CMD ["python", "-m", "app.main"]
