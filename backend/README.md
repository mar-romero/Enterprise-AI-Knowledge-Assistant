# copilot-backend

Minimal FastAPI backend exposing a `GET /health` endpoint.

## Setup

```bat
cd backend
python -m pip install fastapi httpx pytest
```

Dependencies are pinned in `pyproject.toml` to the versions verified in this
environment.

## Run (local development)

```bat
python -m uvicorn app.main:app --port 8000
```

## Tests (canonical deterministic gate)

```bat
python -m unittest discover -s tests -v
```

The same tests also run under pytest:

```bat
python -m pytest tests -q
```

Tests are offline-only: they use `fastapi.testclient.TestClient` in-process
and never bind a real port or make network calls.
