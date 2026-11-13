"""Offline tests for the golden evaluation runner (unittest and pytest).

Covers the golden-set contract, the mirrored ``rag`` abstention gate,
report determinism, CLI exit codes and report round-trip, fail-closed
validation, the TOP_K/THRESHOLD mutation kill and the explicit coupling to
the ``rag.THRESHOLD`` / ``rag.TOP_K`` constants.
"""

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import documents, rag  # noqa: E402
from app import eval as eval_runner  # noqa: E402

CASES = Path(__file__).resolve().parents[2] / "cases" / "mvp-golden-001.json"


class GoldenEvalRunnerTest(unittest.TestCase):
    """Each run uses a fresh storage root; temporary directories are cleaned."""

    def setUp(self) -> None:
        self.directories: list[Path] = []

    def tearDown(self) -> None:
        for directory in self.directories:
            shutil.rmtree(directory, ignore_errors=True)

    def _fresh_root(self) -> Path:
        root = Path(tempfile.mkdtemp())
        self.directories.append(root)
        return root

    def _write_cases(self, cases: list[dict], note: str = "test fixture") -> Path:
        path = Path(tempfile.mkdtemp()) / "cases-fixture.json"
        self.directories.append(path.parent)
        path.write_text(
            json.dumps({"_format_note": note, "cases": cases}, indent=2),
            encoding="utf-8",
        )
        return path

    def test_rag_constants_dependency_documented(self) -> None:
        """The runner mirrors the rag gate: pin the constants it reads live."""
        self.assertEqual(rag.THRESHOLD, 0.5)
        self.assertEqual(rag.TOP_K, 4)

    def _golden_report(self) -> dict:
        return eval_runner.run_eval(CASES, storage_root=self._fresh_root())

    def _by_case_id(self, report: dict) -> dict:
        return {case["case_id"]: case for case in report["cases"]}

    def test_eval_report_rates_on_golden_set(self) -> None:
        report = self._golden_report()
        summary = report["summary"]
        self.assertEqual(summary["retrieval_hit_rate"], 0.8)
        self.assertEqual(summary["abstention_accuracy"], 1.0)
        self.assertEqual(summary["keywords_coverage_rate"], 1.0)
        self.assertTrue(summary["pass"])
        self.assertEqual(summary["total"], 6)

        raw = json.loads(CASES.read_text(encoding="utf-8"))
        content_by_id = {c["case_id"]: c["document"]["content_text"] for c in raw["cases"]}
        cases = self._by_case_id(report)

        refund_sha = hashlib.sha256(
            content_by_id["refund-001"].encode("utf-8")
        ).hexdigest()
        refund = cases["refund-001"]
        self.assertTrue(refund["hit"])
        self.assertEqual(refund["top_score"], 0.8)
        self.assertTrue(refund["top_locator"].endswith("--chunk-2"))
        self.assertTrue(refund["top_locator"].startswith(refund_sha))

        onboarding = cases["onboarding-002"]
        self.assertTrue(onboarding["hit"])
        self.assertEqual(onboarding["top_score"], 1.0)

        compliance = cases["compliance-006"]
        self.assertTrue(compliance["hit"])
        self.assertEqual(compliance["top_score"], 0.8)
        self.assertTrue(compliance["top_locator"].endswith("--chunk-1"))

        pto = cases["pto-003"]
        self.assertTrue(pto["abstained"])
        self.assertFalse(pto["gate_correct"])
        self.assertFalse(pto["hit"])

    def test_eval_exit_code_passes_at_default_threshold(self) -> None:
        self.assertEqual(eval_runner.main(["--cases", str(CASES)]), 0)

    def test_eval_exit_code_fails_below_threshold(self) -> None:
        self.assertEqual(
            eval_runner.main(["--cases", str(CASES), "--min-hit-rate", "0.9"]), 1
        )

    def test_eval_abstain_case_detected(self) -> None:
        abstain = self._by_case_id(self._golden_report())["abstain-004"]
        self.assertTrue(abstain["abstained"])
        self.assertTrue(abstain["gate_correct"])
        self.assertEqual(abstain["top_score"], 0.0)
        self.assertEqual(abstain["keywords_found"], {})
        self.assertFalse(abstain["keywords_covered"])

    def test_eval_boundary_case_hits_at_05(self) -> None:
        boundary = self._by_case_id(self._golden_report())["boundary-005"]
        self.assertFalse(boundary["abstained"])
        self.assertEqual(boundary["top_score"], 0.5)
        self.assertTrue(boundary["hit"])
        self.assertTrue(boundary["keywords_covered"])

    def test_eval_deterministic_two_runs_identical(self) -> None:
        first = eval_runner.run_eval(CASES, storage_root=self._fresh_root())
        second = eval_runner.run_eval(CASES, storage_root=self._fresh_root())
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )

    def test_eval_cli_report_file_written(self) -> None:
        out_path = self._fresh_root() / "report.json"
        exit_code = eval_runner.main(
            ["--cases", str(CASES), "--report", str(out_path)]
        )
        self.assertEqual(exit_code, 0)
        report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["threshold_min"], 0.8)
        self.assertTrue(report["summary"]["pass"])

    def test_eval_dynamic_rag_constants(self) -> None:
        """Mutation killer: THRESHOLD/TOP_K must be read at call time."""
        with mock.patch.object(rag, "THRESHOLD", 0.6):
            report = self._golden_report()
            summary = report["summary"]
            self.assertEqual(summary["retrieval_hit_rate"], 0.6)  # 3/5 hit cases
            self.assertEqual(summary["abstention_accuracy"], 1.0)
            boundary = self._by_case_id(report)["boundary-005"]
            self.assertTrue(boundary["abstained"])
            self.assertFalse(boundary["gate_correct"])
            self.assertFalse(boundary["hit"])

        with mock.patch.object(rag, "TOP_K", 1):
            report = self._golden_report()
            self.assertEqual(report["summary"]["retrieval_hit_rate"], 0.8)

            mini = self._write_cases(
                [
                    {
                        "case_id": "locator-depth-001",
                        "document": {
                            "filename": "locate.md",
                            "content_text": "refund policy within thirty days\n\nrefund",
                        },
                        "question": "refund policy within thirty days",
                        "expected": {
                            "kind": "hit",
                            "expected_locator_chunk_index": 2,
                            "expected_answer_keywords": [],
                        },
                        "note": "chunk-1 = 5/5 tokens at top-1; expected locator is "
                        "chunk-2 (1/5), only retrievable when k >= 2.",
                    }
                ]
            )
            mini_report = eval_runner.run_eval(mini, storage_root=self._fresh_root())
        self.assertFalse(mini_report["cases"][0]["hit"])
        self.assertEqual(mini_report["summary"]["retrieval_hit_rate"], 0.0)

        unpatched = eval_runner.run_eval(mini, storage_root=self._fresh_root())
        self.assertTrue(unpatched["cases"][0]["hit"])
        self.assertEqual(unpatched["summary"]["retrieval_hit_rate"], 1.0)

    def test_eval_exit_requires_abstention_accuracy(self) -> None:
        cases_path = self._write_cases(
            [
                {
                    "case_id": "abstain-flip-001",
                    "document": {
                        "filename": "flip.md",
                        "content_text": "refund policies flourish",
                    },
                    "question": "refund policies",
                    "expected": {
                        "kind": "abstain",
                        "expected_locator_chunk_index": None,
                        "expected_answer_keywords": [],
                    },
                    "note": "gate passes (score 2/2 = 1.0) though kind is abstain.",
                },
                {
                    "case_id": "hit-anchor-001",
                    "document": {
                        "filename": "anchor.md",
                        "content_text": "onboarding buddy",
                    },
                    "question": "onboarding buddy",
                    "expected": {
                        "kind": "hit",
                        "expected_locator_chunk_index": 1,
                        "expected_answer_keywords": [],
                    },
                    "note": "2/2 = 1.0 -> hit.",
                },
            ]
        )
        report = eval_runner.run_eval(cases_path, storage_root=self._fresh_root())
        self.assertEqual(report["summary"]["abstention_accuracy"], 0.0)
        with self.subTest("exit 1 even with min-hit-rate 0.0"):
            self.assertEqual(
                eval_runner.main(
                    ["--cases", str(cases_path), "--min-hit-rate", "0.0"]
                ),
                1,
            )

    def test_eval_malformed_cases_fail_closed(self) -> None:
        broken_root = self._fresh_root()

        not_json = broken_root / "not-json.json"
        not_json.write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            eval_runner.run_eval(not_json, storage_root=self._fresh_root())

        missing_question = self._write_cases(
            [
                {
                    "case_id": "missing-question-001",
                    "document": {"filename": "doc.md", "content_text": "text"},
                    "expected": {
                        "kind": "hit",
                        "expected_locator_chunk_index": 1,
                        "expected_answer_keywords": [],
                    },
                }
            ]
        )
        with self.assertRaises(ValueError):
            eval_runner.run_eval(missing_question, storage_root=self._fresh_root())

        unknown_kind = self._write_cases(
            [
                {
                    "case_id": "unknown-kind-001",
                    "document": {"filename": "doc.md", "content_text": "text"},
                    "question": "question only",
                    "expected": {
                        "kind": "maybe",
                        "expected_locator_chunk_index": 1,
                        "expected_answer_keywords": [],
                    },
                },
                {
                    "case_id": "unknown-kind-anchor",
                    "document": {"filename": "anchor.md", "content_text": "text"},
                    "question": "anchor",
                    "expected": {
                        "kind": "hit",
                        "expected_locator_chunk_index": 1,
                        "expected_answer_keywords": [],
                    },
                },
            ]
        )
        with self.assertRaises(ValueError):
            eval_runner.run_eval(unknown_kind, storage_root=self._fresh_root())

    def test_eval_empty_cases_fail_closed(self) -> None:
        empty = self._write_cases([])
        with self.assertRaises(ValueError):
            eval_runner.run_eval(empty, storage_root=self._fresh_root())

        only_abstain = self._write_cases(
            [
                {
                    "case_id": "only-abstain-001",
                    "document": {"filename": "doc.md", "content_text": "unrelated"},
                    "question": "unrelated words",
                    "expected": {
                        "kind": "abstain",
                        "expected_locator_chunk_index": None,
                        "expected_answer_keywords": [],
                    },
                }
            ]
        )
        with self.assertRaises(ValueError):
            eval_runner.run_eval(only_abstain, storage_root=self._fresh_root())

    def test_eval_duplicate_content_raises(self) -> None:
        duplicated = self._write_cases(
            [
                {
                    "case_id": "dup-a-001",
                    "document": {"filename": "doc.md", "content_text": "same bytes"},
                    "question": "same",
                    "expected": {
                        "kind": "hit",
                        "expected_locator_chunk_index": 1,
                        "expected_answer_keywords": [],
                    },
                },
                {
                    "case_id": "dup-b-001",
                    "document": {"filename": "doc.md", "content_text": "same bytes"},
                    "question": "same",
                    "expected": {
                        "kind": "hit",
                        "expected_locator_chunk_index": 1,
                        "expected_answer_keywords": [],
                    },
                },
            ]
        )
        with self.assertRaises(ValueError) as caught:
            eval_runner.run_eval(duplicated, storage_root=self._fresh_root())
        message = str(caught.exception)
        self.assertIn("dup-a-001", message)
        self.assertIn("dup-b-001", message)

    def test_eval_never_imports_boto3(self) -> None:
        import app.eval  # noqa: F401  (explicit import under test)

        self.assertNotIn("boto3", sys.modules)
        report = self._golden_report()
        self.assertEqual(len(report["cases"]), 6)
        self.assertNotIn("boto3", sys.modules)


if __name__ == "__main__":
    unittest.main()
