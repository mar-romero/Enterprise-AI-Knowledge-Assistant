"""Document ingestion API.

Exposes POST /documents and GET /documents on top of a pluggable storage
abstraction (``StorageBackend``). The default backend is
``LocalDirectoryStorage``, which persists uploaded bytes under a ``files/``
directory and keeps the document registry in a ``registry.json`` file.

The registry file has a known single-process limitation: reads and writes use
one in-memory registry object with a plain read-modify-write cycle, so there is
no concurrency guarantee if multiple processes write to the same
``registry.json`` at the same time. Acceptable for the MVP single-process
deployment; a real multi-process deployment needs a locked or transactional
backend (documented in backend/README.md).

The module is offline-testable: no network calls, no boto3, stdlib + FastAPI
imports only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

ALLOWED_EXTENSIONS = {".pdf", ".md", ".txt"}
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class DocumentMetadata:
    """Metadata record persisted in the registry JSON."""

    id: str
    filename: str
    sha256: str
    size: int
    uploaded_at: str
    duplicate: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "sha256": self.sha256,
            "size": self.size,
            "uploaded_at": self.uploaded_at,
            "duplicate": self.duplicate,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DocumentMetadata:
        return cls(
            id=data["id"],
            filename=data["filename"],
            sha256=data["sha256"],
            size=data["size"],
            uploaded_at=data["uploaded_at"],
            duplicate=data["duplicate"],
        )


class StorageBackend(Protocol):
    """Minimal storage contract for the document ingestion router."""

    def save(self, filename: str, content: bytes) -> DocumentMetadata:
        """Store ``content`` and return its metadata record."""

    def list_documents(self) -> list[DocumentMetadata]:
        """Return all registry records."""


class LocalDirectoryStorage:
    """Filesystem-backed storage rooted at ``root``.

    Layout: ``root/files/<sha256>--<sanitized filename>`` for stored bytes and
    ``root/registry.json`` for metadata records. Writes of the registry are
    atomic via a temporary file and ``os.replace``.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.files_dir = self.root / "files"
        self.registry_path = self.root / "registry.json"

    def _ensure_layout(self) -> None:
        """Create files/ and an empty registry.json on first write.

        Directory creation is deferred to the first save so that importing
        ``app.main`` (which wires the default storage) has no filesystem
        side effects in read-only or test contexts.
        """

        self.files_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write_registry([])

    def _read_registry(self) -> list[DocumentMetadata]:
        if not self.registry_path.exists():
            return []
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return [DocumentMetadata.from_dict(item) for item in raw]

    def _write_registry(self, records: list[DocumentMetadata]) -> None:
        tmp_path = self.registry_path.with_suffix(".json.tmp")
        payload = json.dumps([record.to_dict() for record in records])
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, self.registry_path)

    def _stored_path(self, record: DocumentMetadata) -> Path:
        return self.files_dir / f"{record.sha256}--{_sanitize(record.filename)}"

    def save(self, filename: str, content: bytes) -> DocumentMetadata:
        self._ensure_layout()
        registry = self._read_registry()
        content_sha256 = hashlib.sha256(content).hexdigest()
        for record in registry:
            if record.sha256 == content_sha256:
                existing = DocumentMetadata(
                    id=record.id,
                    filename=record.filename,
                    sha256=record.sha256,
                    size=record.size,
                    uploaded_at=record.uploaded_at,
                    duplicate=True,
                )
                return existing
        record = DocumentMetadata(
            id=content_sha256,
            filename=filename,
            sha256=content_sha256,
            size=len(content),
            uploaded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._stored_path(record).write_bytes(content)
        registry.append(record)
        self._write_registry(registry)
        return record

    def list_documents(self) -> list[DocumentMetadata]:
        return self._read_registry()


class S3StorageBackend(StorageBackend):
    """Documented stub for the future S3 storage backend.

    This is the AWS SDK integration point for the next stage: save and listing
    are intentionally not implemented in the MVP (offline determinism).
    """

    def save(self, filename: str, content: bytes) -> DocumentMetadata:
        raise NotImplementedError(
            "S3 backend is a documented stub, not implemented in the MVP"
        )

    def list_documents(self) -> list[DocumentMetadata]:
        raise NotImplementedError(
            "S3 backend is a documented stub, not implemented in the MVP"
        )


_default_storage: StorageBackend | None = None


def configure_storage(backend: StorageBackend) -> None:
    """Set the module-level default storage used by the router dependency."""

    global _default_storage
    _default_storage = backend


def get_storage() -> StorageBackend:
    if _default_storage is None:
        raise HTTPException(
            status_code=500, detail="default storage not configured"
        )
    return _default_storage


def _sanitize(filename: str) -> str:
    """Restrict a filename to a safe basename for local filesystem storage."""

    base = Path(filename).name
    safe = _SAFE_FILENAME_RE.sub("_", base)
    return safe if safe else "unnamed"


documents_router = APIRouter()


@documents_router.post("/documents", status_code=201)
def upload_document(
    file: UploadFile = File(...),
    storage: StorageBackend = Depends(get_storage),
) -> dict:
    """Upload a document; 201 on first upload, 200 on duplicate."""

    filename = file.filename or ""
    if not filename:
        raise HTTPException(status_code=400, detail="missing filename")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported extension")
    content = file.file.read()
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="file exceeds maximum size")
    record = storage.save(filename, content)
    body = record.to_dict()
    if record.duplicate:
        return JSONResponse(status_code=200, content=body)
    return body


@documents_router.get("/documents")
def list_document_metadata(
    storage: StorageBackend = Depends(get_storage),
) -> list[dict]:
    """List all uploaded document metadata records."""

    return [record.to_dict() for record in storage.list_documents()]
