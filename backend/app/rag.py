"""RAG answer flow (planning decision D8).

Exposes POST /answer on top of a pluggable retrieval abstraction
(``Retriever``). The MVP retriever is ``LocalLexicalRetriever``, a fully
offline lexical retriever over the storage built in ``app.documents``; it
splits UTF-8-decodable ``.txt``/``.md`` content files into blank-line
paragraphs and scores them against the question.

Contract (decision D8):

- The retrieval-only abstention gate runs **before** the LLM call: when the
  registry is empty, no chunk is retrievable, or the best chunk score is
  below ``THRESHOLD``, the endpoint returns HTTP 200 with
  ``{"answer": "", "citations": [], "abstained": True,
  "reason": "INSUFFICIENT_EVIDENCE"}`` and the LLM is never invoked.
- Citations are derived only from retrieved chunks whose sha256 is present
  in the current storage registry; chunks referencing absent documents are
  filtered out defensively.
- PDF and otherwise binary bytes are treated as non-retrievable: content
  that is not UTF-8-decodable (or empty after decoding) contributes nothing.
- A Bedrock Knowledge Bases integration slots in later as another
  ``Retriever`` implementation behind ``configure_retriever``.
- Single-process, mirroring ``app.documents``: no concurrency guarantee.

Scoring formula (deterministic, no randomness): tokens are
``re.findall(r"[a-z0-9]+", text.lower())`` on the question and each chunk;
``score(chunk) = (number of distinct query tokens present in the chunk) /
(number of distinct query tokens)``, and ``0.0`` when the question has no
alphanumeric tokens. Candidates are sorted by score descending, ties by
locator ascending.

The module is offline-testable: no network calls, no cloud SDK imports,
stdlib + FastAPI imports only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Body, Depends, HTTPException

from app import documents
from app.llm import LLMResult

TOP_K = 4
THRESHOLD = 0.5
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_TEXT_EXTENSIONS = (".txt", ".md")


@dataclass(frozen=True)
class Chunk:
    """A retrievable text passage with its citation coordinates."""

    text: str
    doc_id: str
    sha256: str
    locator: str
    score: float


class Retriever(Protocol):
    """Retrieval contract; a Bedrock Knowledge Bases retriever slots in here."""

    def retrieve(self, question: str, k: int) -> list[Chunk]:
        ...


class AnsweringLLM(Protocol):
    """Minimal LLM contract consumed by the /answer route."""

    def answer(self, prompt: str) -> LLMResult:
        ...


class LocalLexicalRetriever:
    """Blank-line paragraph retriever over a ``LocalDirectoryStorage``.

    Only ``.txt``/``.md`` documents whose content file decodes as UTF-8 are
    retrievable; PDF uploads, binary bytes and missing files contribute
    nothing. Chunks without any alphanumeric token are dropped.
    """

    def __init__(self, storage: documents.StorageBackend) -> None:
        self.storage = storage

    def retrieve(self, question: str, k: int) -> list[Chunk]:
        files_dir = getattr(self.storage, "files_dir", None)
        list_documents = getattr(self.storage, "list_documents", None)
        if files_dir is None or not callable(list_documents):
            raise ValueError(
                "LocalLexicalRetriever requires a storage exposing "
                "'files_dir' and 'list_documents'"
            )

        query_tokens = frozenset(_TOKEN_RE.findall(question.lower()))
        candidates: list[Chunk] = []
        for meta in list_documents():
            filename = getattr(meta, "filename", None)
            sha256 = getattr(meta, "sha256", None)
            if not isinstance(filename, str) or not isinstance(sha256, str):
                continue
            lowered = filename.lower()
            extension = Path(filename).suffix.lower()
            if lowered.endswith(".pdf") or extension not in _TEXT_EXTENSIONS:
                continue
            text = self._read_text(Path(files_dir), sha256)
            if text is None:
                continue
            emitted = 0
            for paragraph in _PARAGRAPH_SPLIT_RE.split(text):
                paragraph_tokens = set(_TOKEN_RE.findall(paragraph.lower()))
                if not paragraph_tokens:
                    continue
                emitted += 1
                candidates.append(
                    Chunk(
                        text=paragraph,
                        doc_id=sha256,
                        sha256=sha256,
                        locator=f"{sha256}--chunk-{emitted}",
                        score=self._score(paragraph_tokens, query_tokens),
                    )
                )
        candidates.sort(key=lambda chunk: (-chunk.score, chunk.locator))
        if k <= 0:
            return []
        return candidates[:k]

    @staticmethod
    def _score(chunk_tokens: set[str], query_tokens: frozenset[str]) -> float:
        if not query_tokens:
            return 0.0
        return len(chunk_tokens & query_tokens) / len(query_tokens)

    @staticmethod
    def _read_text(files_dir: Path, sha256: str) -> str | None:
        """Return the first UTF-8-decodable content file for ``sha256``."""
        if not files_dir.is_dir():
            return None
        for path in sorted(files_dir.iterdir()):
            if not path.name.startswith(f"{sha256}--"):
                continue
            try:
                raw = path.read_bytes()
            except OSError:  # missing/unreadable file contributes nothing
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if not text:
                continue
            return text
        return None


_default_llm: AnsweringLLM | None = None
_default_retriever: Retriever | None = None


def configure_llm(llm: AnsweringLLM) -> None:
    """Set the module-level default LLM used by the /answer dependency."""
    global _default_llm
    _default_llm = llm


def configure_retriever(retriever: Retriever) -> None:
    """Set the module-level default retriever used by the /answer dependency."""
    global _default_retriever
    _default_retriever = retriever


def get_llm() -> AnsweringLLM:
    """FastAPI dependency returning the configured LLM."""
    if _default_llm is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "LLM not configured; set via rag.configure_llm or the "
                "AWS_INTEGRATION integration path"
            ),
        )
    return _default_llm


def get_retriever() -> Retriever:
    """FastAPI dependency returning the configured retriever."""
    if _default_retriever is not None:
        return _default_retriever
    return LocalLexicalRetriever(documents.get_storage())


def _question_from_body(payload: dict = Body(...)) -> str:
    """Validate the request body and return the question."""
    question = payload.get("question") if isinstance(payload, dict) else None
    if not isinstance(question, str) or not question.strip():
        raise HTTPException(status_code=400, detail="missing question")
    return question


rag_router = APIRouter()


@rag_router.post("/answer")
def answer(
    question: str = Depends(_question_from_body),
    storage: documents.StorageBackend = Depends(documents.get_storage),
    retriever: Retriever = Depends(get_retriever),
    llm: AnsweringLLM = Depends(get_llm),
) -> dict:
    """Answer a question strictly from retrieved, registry-backed chunks."""
    chunks = retriever.retrieve(question, TOP_K)
    if (
        not storage.list_documents()
        or not chunks
        or chunks[0].score < THRESHOLD
    ):
        return {
            "answer": "",
            "citations": [],
            "abstained": True,
            "reason": "INSUFFICIENT_EVIDENCE",
        }

    prompt_lines = [
        "Answer only from the following excerpt. Cite nothing beyond it.",
        question,
    ]
    for chunk in chunks:
        prompt_lines.append(f"[{chunk.locator}] {chunk.text}")
    result = llm.answer("\n".join(prompt_lines))

    filename_by_sha = {
        meta.sha256: meta.filename for meta in storage.list_documents()
    }
    citations = []
    for chunk in chunks:
        filename = filename_by_sha.get(chunk.sha256)
        if filename is None:
            continue  # defensive: never cite a document absent from the registry
        citations.append(
            {
                "doc_id": chunk.sha256,
                "filename": filename,
                "locator": chunk.locator,
                "score": chunk.score,
            }
        )
    return {"answer": result.text, "citations": citations, "abstained": False}
