# Mayedge Backend

FastAPI backend for the personal Lighter perp desk.

## Setup

```bash
cd backend
cp .env.example .env
# Edit .env with your Lighter API key (index 2-254) and account index
uv sync
uv run mayedge
```

Public market data works without credentials. Trading requires a configured API key.

## Tests

```bash
cd backend
uv run python -m unittest discover -s tests -v
```
