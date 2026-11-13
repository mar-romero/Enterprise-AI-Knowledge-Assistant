"""Golden evaluation runner for the MVP RAG retrieval gate.

Runs the offline golden set ``cases/mvp-golden-001.json`` against a fresh,
locally seeded storage and the *same* retrieval/abstention gate the
``/answer`` endpoint uses (``rag.LocalLexicalRetriever`` +
``rag.THRESHOLD``). The LLM is never imported or called: this module reads
only module attributes of ``app.rag`` (``THRESHOLD``, ``TOP_K``) and the
retriever, so running an evaluation involves no model, no network and no
credentials.

Golden-case schema (also mirrored by the ``_format_note`` key of the cases
file)::

    {
      "_format_note": str,
      "cases": [
        {
          "case_id": str,
          "document": {"filename": ".md or .txt only", "content_text": str},
          "question": str,
          "expected": {
            "kind": "hit" | "abstain",
            "expected_locator_chunk_index": int | null,
            "expected_answer_keywords": [str, ...],
          },
          "note": str,  # exact token-overlap arithmetic for the case
        },
        ...
      ]
    }

Scoring (identical to ``app.rag``): tokens are
``re.findall(r"[a-z0-9]+", text.lower())``; a chunk scores
``|distinct chunk tokens intersect distinct query tokens| /
|distinct query tokens|``. Documents seeded via ``app.documents.save``
(``content_sha256`` is the storage id) are split on blank lines into
1-based paragraphs, so ``locator = f"{content_sha256}--chunk-{n}"``. The
abstention gate mirrors ``rag``'s ``/answer`` gate: abstain iff there are
no documents, no retrievable chunks, or ``best_score < rag.THRESHOLD``.

Offline-determinism contract:

- every ``run_eval`` call seeds a fresh ``LocalDirectoryStorage`` (a new
  temporary directory unless ``storage_root`` is given) exclusively via
  ``app.documents.save``; the module-level default storage singleton is
  never touched;
- the LLM is never imported or called; every rate in the report is a
  deterministic function of the cases file plus ``rag.THRESHOLD`` /
  ``rag.TOP_K`` read at call time;
- the returned report contains no timestamps, no temporary paths and no
  storage-registry metadata, so two runs over the same cases file produce
  byte-identical JSON;
- the repository root is resolved as ``Path(__file__).resolve().parents[2]``
  (``backend/app/eval.py`` -> repository root) for the default cases path.

CLI usage (from the repository root)::

    python backend/app/eval.py --cases cases/mvp-golden-001.json
    python backend/app/eval.py --report <out.json> --min-hit-rate 0.8

Exit status is 0 iff ``retrieval_hit_rate >= min_hit_rate`` AND
``abstention_accuracy == 1.0`` (a mislabeled abstention can never pass).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):  # executed directly: python backend/app/eval.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import documents, rag  # noqa: E402

DEFAULT_MIN_HIT_RATE = 0.8

_VALID_KINDS = ("hit", "abstain")
VALID_DOCUMENT_SUFFIXES = (".md", ".txt")


def run_eval(
    cases_path: str | Path,
    storage_root: str | Path | None = None,
    top_k: int | None = None,
    min_hit_rate: float = DEFAULT_MIN_HIT_RATE,
) -> dict:
    """Run the golden cases and return a deterministic JSON-safe report.

    Fail closed: any missing/invalid structure in the cases file raises
    ``ValueError`` instead of silently producing a misleading report.
    """
    cases = _load_cases(Path(cases_path))

    root = Path(tempfile.mkdtemp()) if storage_root is None else Path(storage_root)
    storage = documents.LocalDirectoryStorage(root=root)
    for case in cases:
        storage.save(
            case["document"]["filename"],
            case["document"]["content_text"].encode("utf-8"),
        )

    retriever = rag.LocalLexicalRetriever(storage)
    k = top_k if top_k is not None else rag.TOP_K

    results = [_evaluate_case(case, retriever, storage, k) for case in cases]
    summary = _summarize(results, min_hit_rate)
    return {"cases": results, "summary": summary}


def _load_cases(cases_path: Path) -> list[dict]:
    """Validate and return the golden cases; raise ``ValueError`` if invalid."""
    path = Path(cases_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"golden cases file cannot be read: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"golden cases file is not valid JSON: {path}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list) or not raw["cases"]:
        raise ValueError(f"golden cases file is empty or invalid: {path}")

    cases = raw["cases"]
    contents_by_sha: dict[str, list[str]] = {}
    has_hit_case = False

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"golden case #{index} is not an object: {path}")
        case_id = case.get("case_id")
        document = case.get("document")
        expected = case.get("expected")

        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"golden case #{index} is missing a string 'case_id': {path}")
        if not isinstance(case.get("question"), str) or not case["question"]:
            raise ValueError(f"golden case '{case_id}' is missing a string 'question': {path}")
        if not isinstance(document, dict) or not isinstance(document.get("content_text"), str):
            raise ValueError(
                f"golden case '{case_id}' is missing a string 'document.content_text': {path}"
            )
        filename = document.get("filename")
        if (
            not isinstance(filename, str)
            or Path(filename).suffix.lower() not in VALID_DOCUMENT_SUFFIXES
        ):
            raise ValueError(
                f"golden case '{case_id}' needs a .md/.txt 'document.filename': {path}"
            )

        if not isinstance(expected, dict) or "kind" not in expected:
            raise ValueError(f"golden case '{case_id}' is missing 'expected.kind': {path}")
        kind = expected["kind"]
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"golden case '{case_id}' has unknown expected.kind {kind!r}: {path}"
            )
        if kind == "hit":
            has_hit_case = True
            chunk_index = expected.get("expected_locator_chunk_index")
            if not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 1:
                raise ValueError(
                    f"golden case '{case_id}' of kind 'hit' needs an int "
                    f"'expected.expected_locator_chunk_index' >= 1: {path}"
                )
        keywords = expected.get("expected_answer_keywords", [])
        if not isinstance(keywords, list) or not all(
            isinstance(keyword, str) for keyword in keywords
        ):
            raise ValueError(
                f"golden case '{case_id}' needs a list of strings "
                f"'expected.expected_answer_keywords': {path}"
            )

        content_sha = hashlib.sha256(document["content_text"].encode("utf-8")).hexdigest()
        contents_by_sha.setdefault(content_sha, []).append(case_id)

    colliding = [case_ids for case_ids in contents_by_sha.values() if len(case_ids) > 1]
    if colliding:
        names = "; ".join(" + ".join(case_ids) for case_ids in colliding)
        raise ValueError(f"duplicate document content across golden cases: {names}")
    if not has_hit_case:
        raise ValueError(f"golden cases file contains no 'hit' case: {path}")

    return cases


def _evaluate_case(case: dict, retriever: object, storage: object, k: int) -> dict:
    """Evaluate one golden case through the ``rag`` gate; no I/O side effects."""
    question: str = case["question"]
    expected: dict = case["expected"]
    kind: str = expected["kind"]
    content_text: str = case["document"]["content_text"]
    content_sha = hashlib.sha256(content_text.encode("utf-8")).hexdigest()

    retrieved = retriever.retrieve(question, k)

    # Mirrors the /answer gate in app.rag exactly; reads rag.THRESHOLD live.
    gate = (
        (not storage.list_documents())
        or (not retrieved)
        or (retrieved[0].score < rag.THRESHOLD)
    )
    abstained = bool(gate)
    gate_correct = abstained == (kind == "abstain")

    top = retrieved[0] if retrieved else None
    if kind == "hit":
        expected_locator = f"{content_sha}--chunk-{expected['expected_locator_chunk_index']}"
    else:
        expected_locator = None
    expected_locator_retrieved = (
        expected_locator is not None and any(c.locator == expected_locator for c in retrieved)
    )

    keywords: list[str] = list(expected.get("expected_answer_keywords") or [])
    top_hit_chunk = next((c for c in retrieved if c.doc_id == content_sha), None)
    keywords_found: dict[str, bool] = {}
    if kind == "hit" and keywords and top_hit_chunk is not None:
        lowered = top_hit_chunk.text.lower()
        keywords_found = {keyword: keyword.lower() in lowered for keyword in keywords}
    keywords_covered = all(keywords_found.values()) if keywords_found else False

    hit = (
        kind == "hit"
        and not abstained
        and (expected_locator_retrieved or keywords_covered)
    )

    return {
        "case_id": case["case_id"],
        "expected_kind": kind,
        "abstained": abstained,
        "gate_correct": gate_correct,
        "hit": hit,
        "top_score": round(top.score, 6) if top is not None else 0.0,
        "top_locator": top.locator if top is not None else None,
        "expected_locator": expected_locator,
        "expected_locator_retrieved": expected_locator_retrieved,
        "keywords_found": keywords_found,
        "keywords_covered": keywords_covered,
    }


def _summarize(results: list[dict], min_hit_rate: float) -> dict:
    """Compute rounded, byte-stable rates (fail closed on empty partitions)."""
    hit_cases = [result for result in results if result["expected_kind"] == "hit"]
    abstain_cases = [result for result in results if result["expected_kind"] == "abstain"]
    keyword_cases = [result for result in hit_cases if result["keywords_found"]]

    retrieval_hit_rate = (
        sum(1 for result in hit_cases if result["hit"]) / len(hit_cases)
        if hit_cases
        else 0.0
    )
    abstention_accuracy = (
        sum(1 for result in abstain_cases if result["gate_correct"]) / len(abstain_cases)
        if abstain_cases
        else 0.0
    )
    keywords_coverage_rate = (
        sum(1 for result in keyword_cases if result["keywords_covered"]) / len(keyword_cases)
        if keyword_cases
        else 0.0
    )

    rounded = {
        "total": len(results),
        "retrieval_hit_rate": round(retrieval_hit_rate, 4),
        "abstention_accuracy": round(abstention_accuracy, 4),
        "keywords_coverage_rate": round(keywords_coverage_rate, 4),
        "threshold_min": min_hit_rate,
    }
    rounded["pass"] = bool(
        rounded["retrieval_hit_rate"] >= min_hit_rate
        and rounded["abstention_accuracy"] == 1.0
    )
    return rounded


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; prints one deterministic summary line."""
    default_cases = Path(__file__).resolve().parents[2] / "cases" / "mvp-golden-001.json"
    parser = argparse.ArgumentParser(
        description="Run the offline golden evaluation for the MVP RAG retrieval gate."
    )
    parser.add_argument("--cases", type=Path, default=default_cases)
    parser.add_argument("--min-hit-rate", type=float, default=DEFAULT_MIN_HIT_RATE)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    report = run_eval(args.cases, min_hit_rate=args.min_hit_rate)
    if args.report is not None:
        with args.report.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)

    summary = report["summary"]
    print(
        f"eval: {summary['total']} cases | hit_rate={summary['retrieval_hit_rate']} "
        f"abstention={summary['abstention_accuracy']} "
        f"keywords={summary['keywords_coverage_rate']} pass={summary['pass']}"
    )
    if summary["retrieval_hit_rate"] >= args.min_hit_rate and (
        summary["abstention_accuracy"] == 1.0
    ):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
