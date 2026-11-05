"""Minimal FastAPI application exposing a health endpoint.

Only stdlib + FastAPI imports happen at module import time; no network calls,
background tasks or external clients are initialized on import.
"""

from pathlib import Path

import os

from fastapi import FastAPI

from app import documents

APP_VERSION = "0.1.0"

app = FastAPI(title="copilot-backend", version=APP_VERSION)

documents.configure_storage(
    documents.LocalDirectoryStorage(
        root=Path(os.environ.get("DOCUMENTS_STORAGE_ROOT", "data/documents"))
    )
)
app.include_router(documents.documents_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health status and application version."""
    return {"status": "ok", "version": APP_VERSION}
