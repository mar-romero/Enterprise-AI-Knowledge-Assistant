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

## LLM wrapper (backend/app/llm.py)

Thin Bedrock Converse wrapper, dependency-injected via `BedrockLLM(client,
settings)`; unit tests run offline with a fake client (zero network) and
require no boto3 installation. No identity material is handled in this unit;
the runtime provider configuration is an integration-stage concern.

Environment fields:

- `BEDROCK_MODEL_ID`: model id to use; the empty default means real calls
  require setting it before use.
- `AWS_REGION`: region for the client (default `us-east-1`).
- `AWS_INTEGRATION`: `0`/`1` (default `0`); enables the opt-in integration
  test against real AWS Bedrock.

Real Bedrock calls need boto3 (`python -m pip install boto3`); the module
imports boto3 only lazily inside `build_default_client()`.

Opt-in integration test:

```bat
set AWS_INTEGRATION=1 && python -m pytest tests -q -k Integration
```
