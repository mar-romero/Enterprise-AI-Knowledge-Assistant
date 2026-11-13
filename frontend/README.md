# copilot-frontend

Minimal Next.js 15 (App Router) + React 19 frontend for the Enterprise AI
Copilot MVP. It talks to the FastAPI backend in `../backend`.

## Setup

```bash
cd frontend
npm install
```

`package.json` pins exact stable versions: `next@15.1.6`,
`react@19.0.0`, `react-dom@19.0.0`.

## Run

```bash
npm run dev
```

Then open <http://localhost:3000>.

## Configuration

| Variable                  | Default                 | Purpose                                   |
| ------------------------- | ----------------------- | ----------------------------------------- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Base URL of the backend REST API          |

## Backend requirements

The backend must be running before using the UI, e.g. from `../backend`:

```bash
uvicorn app.main:app
```

For the chat (`/answer`) endpoint the backend also needs an LLM configured;
otherwise `/answer` returns HTTP 500 and the UI shows a corresponding
message. Retrieval-only abstinence (no documents or no sufficient evidence)
is normal and shown as `INSUFFICIENT_EVIDENCE`.

## Backend endpoints consumed

- `GET /health` — backend availability.
- `POST /documents` — multipart upload (`file` field); returns `{id,
  filename, sha256, size, uploaded_at, duplicate}`. `duplicate: true` means
  the exact same content (same sha256) was already registered (dedupe).
- `GET /documents` — list registered document metadata.
- `POST /answer` — JSON `{question}`; returns `{answer, citations,
  abstained[, reason]}`. Citations carry `doc_id`, `filename`, `locator` and
  `score`; the locator identifies the exact source section (chunk) the answer
  was drawn from.
