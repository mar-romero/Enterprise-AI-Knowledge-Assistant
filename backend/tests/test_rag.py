"""Offline tests for the RAG answer flow (unittest discover and pytest)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import documents, rag  # noqa: E402
from app.documents import LocalDirectoryStorage  # noqa: E402
from app.llm import BedrockLLM  # noqa: E402
from app.main import app  # noqa: E402

GOLDEN_POLICY = (
    b"Refund policy overview.\n\n"
    b"The refund is processed within 14 days of the request. Policy details "
    b"are described in this document.\n\n"
    b"Shipping and returns are subject to the same refund rules."
)
UNRELATED_QUESTION = "quantum entanglement experiment"
THRESHOLD_QUESTION = "what is the refund policy"
LATER_DOC = b"alpha beta gamma ray spectrum"
LATER_QUESTION = "alpha beta gamma"
TOP_K_DOC = (
    b"alpha ray detector\n\n"
    b"alpha beta gamma ray spectrum\n\n"
    b"beta gamma decay"
)


class FakeConverseClient:
    """Counts converse invocations and returns a canned grounded response."""

    def __init__(self) -> None:
        self.calls = 0

    def converse(self, model_id: str, messages: list) -> dict:
        self.calls += 1
        return {
            "output": {
                "message": {
                    "content": [{"text": "grounded answer from provided excerpts"}]
                }
            },
            "usage": {
                "inputTokens": 1,
                "outputTokens": 1,
                "totalTokens": 2,
            },
            "stopReason": "end_turn",
        }


class RAGAnswerEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp())
        self.storage = LocalDirectoryStorage(root=self.tmp_root)
        self.fake_client = FakeConverseClient()
        fake_llm = BedrockLLM(client=self.fake_client)
        app.dependency_overrides[documents.get_storage] = lambda: self.storage
        app.dependency_overrides[rag.get_retriever] = lambda: (
            rag.LocalLexicalRetriever(self.storage)
        )
        app.dependency_overrides[rag.get_llm] = lambda: fake_llm
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.pop(documents.get_storage, None)
        app.dependency_overrides.pop(rag.get_retriever, None)
        app.dependency_overrides.pop(rag.get_llm, None)
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _seed_policy(self):
        return self.storage.save("policy.txt", GOLDEN_POLICY)

    def _post_answer(self, question: str):
        return self.client.post("/answer", json={"question": question})

    def test_answer_golden_question_returns_nonempty_citations_and_answer(
        self,
    ) -> None:
        meta = self._seed_policy()
        response = self._post_answer(THRESHOLD_QUESTION)

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is False
        assert "reason" not in body
        assert body["answer"] == "grounded answer from provided excerpts"
        assert len(body["citations"]) == 3
        for citation in body["citations"]:
            assert set(citation) == {"doc_id", "filename", "locator", "score"}
            assert citation["doc_id"] == meta.sha256
            assert citation["filename"] == "policy.txt"
        locators = {citation["locator"] for citation in body["citations"]}
        assert locators == {
            f"{meta.sha256}--chunk-1",
            f"{meta.sha256}--chunk-2",
            f"{meta.sha256}--chunk-3",
        }
        assert any(
            citation["locator"] == f"{meta.sha256}--chunk-2"
            for citation in body["citations"]
        )
        assert body["citations"][0]["score"] >= max(
            citation["score"] for citation in body["citations"]
        )

    def test_answer_below_threshold_abstains_without_llm_call(self) -> None:
        self._seed_policy()
        response = self._post_answer(UNRELATED_QUESTION)

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is True
        assert body["reason"] == "INSUFFICIENT_EVIDENCE"
        assert body["answer"] == ""
        assert body["citations"] == []
        assert self.fake_client.calls == 0

    def test_answer_no_documents_abstains(self) -> None:
        response = self._post_answer(LATER_QUESTION)

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is True
        assert body["reason"] == "INSUFFICIENT_EVIDENCE"
        assert body["answer"] == ""
        assert body["citations"] == []
        assert self.fake_client.calls == 0

    def test_answer_zero_retrievable_chunks_abstains(self) -> None:
        self.storage.save("doc.pdf", b"%PDF-1.4 fake")
        response = self._post_answer(UNRELATED_QUESTION)

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is True
        assert body["reason"] == "INSUFFICIENT_EVIDENCE"
        assert body["answer"] == ""
        assert body["citations"] == []
        assert self.fake_client.calls == 0

    def test_answer_corrupted_content_abstains_file_missing(self) -> None:
        meta = self._seed_policy()
        (self.storage.files_dir / f"{meta.sha256}--policy.txt").unlink()
        response = self._post_answer(THRESHOLD_QUESTION)

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is True
        assert body["reason"] == "INSUFFICIENT_EVIDENCE"
        assert body["answer"] == ""
        assert body["citations"] == []
        assert self.fake_client.calls == 0

    def test_citations_only_reference_list_documents(self) -> None:
        meta = self._seed_policy()
        response = self._post_answer(THRESHOLD_QUESTION)

        assert response.status_code == 200
        body = response.json()
        known_shas = {record.sha256 for record in self.storage.list_documents()}
        assert meta.sha256 in known_shas
        for citation in body["citations"]:
            assert citation["doc_id"] in known_shas

    def test_newly_uploaded_document_becomes_retrievable_same_test(self) -> None:
        before = self._post_answer(LATER_QUESTION)
        assert before.status_code == 200
        assert before.json()["abstained"] is True

        self.storage.save("findme.txt", LATER_DOC)
        after = self._post_answer(LATER_QUESTION)

        assert after.status_code == 200
        body = after.json()
        assert body["abstained"] is False
        assert body["answer"] != ""
        assert [citation["filename"] for citation in body["citations"]] == [
            "findme.txt"
        ]
        assert body["citations"][0]["locator"].endswith("--chunk-1")

    def test_top_k_multi_chunk_ordering(self) -> None:
        meta = self.storage.save("spectrum.txt", TOP_K_DOC)
        response = self._post_answer(LATER_QUESTION)

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is False
        assert [citation["locator"] for citation in body["citations"]] == [
            f"{meta.sha256}--chunk-2",
            f"{meta.sha256}--chunk-3",
            f"{meta.sha256}--chunk-1",
        ]

    def test_pdf_bytes_skipped(self) -> None:
        pdf_meta = self.storage.save("doc.pdf", b"%PDF-1.4 fake")
        self._seed_policy()

        response = self._post_answer(THRESHOLD_QUESTION)

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is False
        assert body["answer"] != ""
        for citation in body["citations"]:
            assert citation["doc_id"] != pdf_meta.sha256
            assert citation["filename"] == "policy.txt"

    def test_answer_deterministic_same_question_twice(self) -> None:
        self._seed_policy()
        first = self._post_answer(THRESHOLD_QUESTION)
        second = self._post_answer(THRESHOLD_QUESTION)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()

    def test_missing_or_empty_question_returns_400(self) -> None:
        missing = self.client.post("/answer", json={})
        empty = self.client.post("/answer", json={"question": "   "})

        assert missing.status_code == 400
        assert missing.json()["detail"] == "missing question"
        assert empty.status_code == 400
        assert empty.json()["detail"] == "missing question"

    def test_health_still_ok(self) -> None:
        response = self.client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


BOUNDARY_DOC = b"alpha stenography"
BOUNDARY_QUESTION = "alpha zulu"
FABRICATED_SHA = "f" * 64
TIE_DOC = "\n\n".join(
    f"alpha filler witness {index}" for index in range(1, 7)
).encode("utf-8")


class StubRetriever:
    """Returns pre-built chunks regardless of the question, for filter tests."""

    def __init__(self, chunks) -> None:
        self.chunks = chunks
        self.retrieve_calls = 0

    def retrieve(self, question: str, k: int) -> list:
        self.retrieve_calls += 1
        return self.chunks


class RAGAuditGapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp())
        self.storage = LocalDirectoryStorage(root=self.tmp_root)
        self.fake_client = FakeConverseClient()
        fake_llm = BedrockLLM(client=self.fake_client)
        app.dependency_overrides[documents.get_storage] = lambda: self.storage
        app.dependency_overrides[rag.get_retriever] = lambda: (
            rag.LocalLexicalRetriever(self.storage)
        )
        app.dependency_overrides[rag.get_llm] = lambda: fake_llm
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.pop(documents.get_storage, None)
        app.dependency_overrides.pop(rag.get_retriever, None)
        app.dependency_overrides.pop(rag.get_llm, None)
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_answer_boundary_score_passes_gate(self) -> None:
        # Distinct chunk tokens {alpha, stenography}; distinct query tokens
        # {alpha, zulu}; overlap {alpha} -> 1/2 == 0.5 == THRESHOLD. The gate
        # must treat "score < THRESHOLD" as passable at exactly THRESHOLD.
        self.storage.save("boundary.txt", BOUNDARY_DOC)
        response = self.client.post(
            "/answer", json={"question": BOUNDARY_QUESTION}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is False
        assert "reason" not in body
        assert body["answer"] == "grounded answer from provided excerpts"
        assert len(body["citations"]) == 1
        assert body["citations"][0]["score"] == 0.5

    def test_fabricated_citations_dropped(self) -> None:
        meta = self.storage.save("real.txt", b"real document body")
        real_chunk = rag.Chunk(
            text="real document body",
            doc_id=meta.sha256,
            sha256=meta.sha256,
            locator=f"{meta.sha256}--chunk-1",
            score=1.0,
        )
        fabricated_chunk = rag.Chunk(
            text="fabricated content",
            doc_id=FABRICATED_SHA,
            sha256=FABRICATED_SHA,
            locator=f"{FABRICATED_SHA}--chunk-1",
            score=1.0,
        )
        stub = StubRetriever([real_chunk, fabricated_chunk])
        app.dependency_overrides[rag.get_retriever] = lambda: stub

        response = self.client.post(
            "/answer", json={"question": "real document body"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is False
        assert self.fake_client.calls == 1
        assert stub.retrieve_calls == 1
        assert [citation["doc_id"] for citation in body["citations"]] == [
            meta.sha256
        ]
        assert all(
            citation["doc_id"] != FABRICATED_SHA
            for citation in body["citations"]
        )
        assert body["citations"][0]["locator"] == f"{meta.sha256}--chunk-1"

    def test_top_k_truncation(self) -> None:
        self.storage.save("ties.txt", TIE_DOC)
        response = self.client.post(
            "/answer", json={"question": "alpha witness"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["abstained"] is False
        assert len(body["citations"]) == rag.TOP_K
        assert rag.TOP_K == 4
        top_doc_id = body["citations"][0]["doc_id"]
        assert [citation["locator"] for citation in body["citations"]] == [
            f"{top_doc_id}--chunk-{index}" for index in range(1, rag.TOP_K + 1)
        ]

    def test_golden_score_pinned_case_insensitive(self) -> None:
        self.storage.save("policy.txt", GOLDEN_POLICY)

        lower = self.client.post("/answer", json={"question": THRESHOLD_QUESTION})
        upper = self.client.post(
            "/answer",
            json={"question": THRESHOLD_QUESTION.upper()},
        )

        assert lower.status_code == 200
        assert upper.status_code == 200
        lower_body = lower.json()
        upper_body = upper.json()
        # {what, is, the, refund, policy} vs chunk-2: {the, is, refund,
        # policy} present -> 4/5 == 0.8, the top score of the golden fixture.
        assert lower_body["abstained"] is False
        assert upper_body["abstained"] is False
        assert lower_body["citations"][0]["score"] == 0.8
        assert upper_body["citations"][0]["score"] == 0.8
        assert (
            lower_body["citations"][0]["score"]
            == upper_body["citations"][0]["score"]
        )
        assert lower_body["citations"][0]["locator"].endswith("--chunk-2")
        assert upper_body["citations"][0]["locator"].endswith("--chunk-2")


if __name__ == "__main__":
    unittest.main()
