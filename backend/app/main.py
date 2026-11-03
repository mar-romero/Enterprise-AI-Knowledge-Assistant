"""Minimal FastAPI application exposing a health endpoint.

Only stdlib + FastAPI imports happen at module import time; no network calls,
background tasks or external clients are initialized on import.
"""

from fastapi import FastAPI

APP_VERSION = "0.1.0"

app = FastAPI(title="copilot-backend", version=APP_VERSION)


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health status and application version."""
    return {"status": "ok", "version": APP_VERSION}
