FROM node:22-alpine AS web

WORKDIR /web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv \
    && mkdir -p /app/data

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
COPY backend/config ./config

RUN uv pip install --system --no-cache .

COPY --from=web /web/dist /app/web

ENV DB_PATH=/app/data/mayedge.db
ENV WEB_ROOT=/app/web
ENV ALERTS_CONFIG=/app/config/alerts.yaml

EXPOSE 8000

CMD ["mayedge"]
