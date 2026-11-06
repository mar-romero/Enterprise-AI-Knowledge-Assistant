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

## RAG answer flow (backend/app/rag.py)

POST /answer implements planning decision D8: a local lexical retriever
(offline, no randomness) with a **retrieval-only abstention gate that runs
BEFORE the LLM call**, so generation only happens when evidence exists.

Retriever mechanics:

- Documents uploaded through `documents.py` are served by
  `LocalDirectoryStorage`: only `.txt`/`.md` files whose stored bytes decode
  as UTF-8 (and are non-empty after decoding) are text-retrievable. PDFs and
  binary bytes are treated as non-retrievable, and a registry record without
  its content file contributes nothing.
- Text is split into blank-line paragraphs (`\n\s*\n`); chunks without any
  alphanumeric token are dropped. Each chunk gets the locator
  `<sha256>--chunk-<n>` where `n` is 1-based in document order.
- Scoring is deterministic case-insensitive token overlap:
  `score(chunk) = (distinct query tokens present in the chunk) / (distinct
  query tokens)`; a question with no alphanumeric tokens scores 0.
  Candidates sort by score descending, ties by locator ascending, and the
  route keeps the top `TOP_K = 4` chunks (`THRESHOLD = 0.5`).
- `BedrockLLM` from `app/llm.py` wraps generation behind the `AnsweringLLM`
  protocol; the `Retriever` protocol (`retrieve(question, k) -> list[Chunk]`)
  is the integration slot where a Bedrock Knowledge Bases retriever can be
  added later as another implementation (`rag.configure_retriever`).
- Like `documents.py`, the flow is single-process: no concurrency guarantee.

Abstention semantics (`INSUFFICIENT_EVIDENCE`):

- Registry empty, zero retrievable chunks, or best chunk score below
  `THRESHOLD` → HTTP 200 with
  `{"answer": "", "citations": [], "abstained": true,
  "reason": "INSUFFICIENT_EVIDENCE"}`; the LLM is never called.
- Otherwise HTTP 200 with `{"answer": <LLM text>, "citations": [...],
  "abstained": false}`; citations reference only retrieved chunks whose
  sha256 is still present in the current storage registry (never absent
  documents).
- `/answer` requires an LLM to be configured via `rag.configure_llm(...)`:
  in the default runtime (nothing configured in `app/main.py`) it returns
  HTTP 500 "LLM not configured; set via rag.configure_llm or the
  AWS_INTEGRATION integration path". No boto3 is imported at module level;
  offline tests inject fakes through FastAPI dependency overrides.

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

### POST /answer

JSON body `{"question": "..."}`:

- `400` `missing question`: the field is absent, not a string, or blank.
- `200`: `{"answer", "citations", "abstained"}` per the semantics of the
  "RAG answer flow (backend/app/rag.py)" section above (with
  `reason: "INSUFFICIENT_EVIDENCE"` on abstention). Each citation carries
  `{doc_id, filename, locator, score}`.

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
