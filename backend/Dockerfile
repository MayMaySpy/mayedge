FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv \
    && mkdir -p /app/data

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY config ./config

RUN uv pip install --system --no-cache .

ENV DB_PATH=/app/data/mayedge.db
ENV ALERTS_CONFIG=/app/config/alerts.yaml

EXPOSE 8000

CMD ["mayedge"]
