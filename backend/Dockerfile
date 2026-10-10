FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv \
    && mkdir -p /app/data

# Install exactly what uv.lock pins, the same set CI tests against.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev --no-editable --no-cache

ENV PATH="/app/.venv/bin:$PATH"

ENV DB_PATH=/app/data/mayedge.db
ENV ALERTS_CONFIG=/app/config/alerts.yaml

EXPOSE 8000

CMD ["mayedge"]
