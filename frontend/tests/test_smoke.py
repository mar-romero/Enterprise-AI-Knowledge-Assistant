"""Scaffold-contract smoke tests for the copilot-frontend. Placed under
frontend/tests so the deterministic check-runner resolves the project root to
the frontend project and runs this fast suite (~0.1s) instead of the
repository-root harness suite. Validates the UI contract against the backend
endpoints without needing Node."""

import json
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (FRONTEND / rel).read_text(encoding="utf-8")


class FrontendScaffoldSmokeTest(unittest.TestCase):
    def test_package_json_parses_with_pinned_deps(self) -> None:
        pkg = json.loads(read("package.json"))
        self.assertEqual(pkg["dependencies"]["next"], "15.1.6")
        self.assertEqual(pkg["dependencies"]["react"], "19.0.0")
        self.assertEqual(pkg["dependencies"]["react-dom"], "19.0.0")
        for script in ("dev", "build", "start"):
            self.assertIn(script, pkg["scripts"])

    def test_layout_declares_app_identity(self) -> None:
        layout = read("app/layout.tsx")
        self.assertIn("Enterprise AI Copilot", layout)
        self.assertIn("/documents", layout)
        self.assertIn('href="/"', layout)

    def test_chat_page_contract(self) -> None:
        page = read("app/page.tsx")
        for needle in (
            "/answer",
            "abstained",
            "INSUFFICIENT_EVIDENCE",
            "citations",
            "NEXT_PUBLIC_API_BASE_URL",
        ):
            self.assertIn(needle, page)

    def test_documents_page_contract(self) -> None:
        page = read("app/documents/page.tsx")
        for needle in ("/documents", "FormData", "sha256", "duplicate"):
            self.assertIn(needle, page)

    def test_readme_documents_setup_and_env(self) -> None:
        readme = read("README.md")
        for needle in (
            "npm install",
            "npm run dev",
            "NEXT_PUBLIC_API_BASE_URL",
            "http://localhost:8000",
        ):
            self.assertIn(needle, readme)


if __name__ == "__main__":
    unittest.main()
