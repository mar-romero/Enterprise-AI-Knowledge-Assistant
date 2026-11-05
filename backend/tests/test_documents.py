"""Offline tests for the document ingestion API (unittest discover and pytest)."""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import documents  # noqa: E402
from app.documents import LocalDirectoryStorage  # noqa: E402
from app.main import app  # noqa: E402


class DocumentEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp())
        self.storage = LocalDirectoryStorage(root=self.tmp_root)
        app.dependency_overrides[documents.get_storage] = lambda: self.storage
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.pop(documents.get_storage, None)
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_upload_txt_returns_201_with_metadata(self) -> None:
        content = b"hello knowledge assistant"
        response = self.client.post(
            "/documents",
            files={"file": ("notes.txt", content, "text/plain")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["filename"] == "notes.txt"
        assert body["sha256"] == hashlib.sha256(content).hexdigest()
        assert body["size"] == len(content)
        assert body["duplicate"] is False
        assert body["id"] != ""
        assert body["uploaded_at"] != ""

    def test_md_and_pdf_supported(self) -> None:
        md_response = self.client.post(
            "/documents",
            files={"file": ("readme.md", b"# title", "text/markdown")},
        )
        pdf_response = self.client.post(
            "/documents",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert md_response.status_code == 201
        assert pdf_response.status_code == 201

    def test_duplicate_reupload_deduped(self) -> None:
        content = b"same bytes twice"
        first = self.client.post(
            "/documents",
            files={"file": ("first.txt", content, "text/plain")},
        )
        second = self.client.post(
            "/documents",
            files={"file": ("second.txt", content, "text/plain")},
        )

        assert first.status_code == 201
        first_body = first.json()
        assert first_body["duplicate"] is False
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["duplicate"] is True
        assert second_body["id"] == first_body["id"]
        assert second_body["sha256"] == first_body["sha256"]
        assert second_body["size"] == first_body["size"]
        assert second_body["uploaded_at"] == first_body["uploaded_at"]

        listing = self.client.get("/documents")
        assert listing.status_code == 200
        assert len(listing.json()) == 1

    def test_unsupported_extension_returns_400(self) -> None:
        response = self.client.post(
            "/documents",
            files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
        )

        assert response.status_code == 400
        assert "unsupported extension" in response.json()["detail"]

    def test_missing_filename_returns_400(self) -> None:
        # httpx's files= convenience maps an empty filename to a plain form
        # field (422), so this test sends the raw multipart part with an
        # explicit empty filename attribute to exercise the route-level check.
        boundary = "B00NDARY"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename=""\r\n'
            "Content-Type: text/plain\r\n"
            "\r\n"
            "data\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        response = self.client.post(
            "/documents",
            content=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}"
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "missing filename"

    def test_oversize_returns_413(self) -> None:
        content = b"x" * (5 * 1024 * 1024 + 1)
        response = self.client.post(
            "/documents",
            files={"file": ("big.txt", content, "text/plain")},
        )

        assert response.status_code == 413
        assert "file exceeds maximum size" in response.json()["detail"]

    def test_cap_boundary(self) -> None:
        content = b"a" * (5 * 1024 * 1024)
        response = self.client.post(
            "/documents",
            files={"file": ("cap.txt", content, "text/plain")},
        )

        assert response.status_code == 201

    def test_empty_file_allowed(self) -> None:
        response = self.client.post(
            "/documents",
            files={"file": ("empty.txt", b"", "text/plain")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["size"] == 0
        assert body["sha256"] == hashlib.sha256(b"").hexdigest()

    def test_registry_persists_across_instances(self) -> None:
        content = b"persist across instances"
        response = self.client.post(
            "/documents",
            files={"file": ("persist.txt", content, "text/plain")},
        )
        assert response.status_code == 201

        second_storage = LocalDirectoryStorage(root=self.tmp_root)
        records = second_storage.list_documents()
        assert len(records) == 1
        assert records[0].sha256 == hashlib.sha256(content).hexdigest()

    def test_get_documents_lists_metadata(self) -> None:
        first = self.client.post(
            "/documents",
            files={"file": ("a.txt", b"alpha", "text/plain")},
        )
        second = self.client.post(
            "/documents",
            files={"file": ("b.md", b"beta", "text/markdown")},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        listing = self.client.get("/documents")
        assert listing.status_code == 200
        entries = listing.json()
        assert len(entries) == 2
        for entry in entries:
            assert "sha256" in entry
            assert "duplicate" in entry

    def test_health_still_ok(self) -> None:
        response = self.client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


if __name__ == "__main__":
    unittest.main()
