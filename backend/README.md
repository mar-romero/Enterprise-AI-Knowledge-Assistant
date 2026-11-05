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

## Endpoints

### POST /documents

Multipart upload of a document (field name `file`). Allowed extensions:
`.pdf`, `.md`, `.txt` (case-insensitive). Maximum size: 5 MB
(`MAX_DOCUMENT_BYTES = 5 * 1024 * 1024`).

Semantics:

- `201`: first upload of the content; returns `{id, filename, sha256, size,
  uploaded_at, duplicate}` with `duplicate=false`.
- `200`: the exact same content (same sha256) was already uploaded; returns
  the existing record with `duplicate=true` and no second blob is stored.
- `400` `unsupported extension`: filename suffix not in the allowed set.
- `400` `missing filename`: empty filename.
- `413` `file exceeds maximum size`: content above the 5 MB cap.
- Empty content (`size=0`) is accepted.

### GET /documents

Returns the list of stored metadata records (`id`, `filename`, `sha256`,
`size`, `uploaded_at`, `duplicate`) as JSON; empty list before any upload.

## Storage (`backend/app/documents.py`)

- `LocalDirectoryStorage`: default backend. Layout under
  `DOCUMENTS_STORAGE_ROOT` (default `data/documents`, relative to the backend
  working directory):
  - `files/<sha256>--<sanitized filename>`: stored bytes (content-addressed;
    duplicates reuse the existing file).
  - `registry.json`: metadata records, appended under a read-modify-write
    cycle and replaced atomically (tmp file + `os.replace`). Known MVP
    limitation: no multi-process concurrency guarantee on `registry.json`.
  - Directory creation is lazy: only the first save writes to disk, so
    importing the app has no filesystem side effects.
- `S3StorageBackend`: documented stub for the AWS SDK integration point;
  `save()`/`list_documents()` raise `NotImplementedError` in this MVP.

Setup note: `python-multipart==0.0.33` is pinned in `pyproject.toml` and is
required for multipart request parsing (unpinned installs fail FastAPI's
multipart upload with a runtime error).
