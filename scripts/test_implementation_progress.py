"""Standard-library checks for progress accounting; no application services needed."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).with_name("implementation_progress.py")
SPEC = importlib.util.spec_from_file_location("implementation_progress", MODULE)
assert SPEC is not None and SPEC.loader is not None
progress = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(progress)


class ProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(progress.DEFAULT_REGISTER.read_text())
        self.sha = "a" * 40

    def test_estimate_is_separate_from_qualification(self) -> None:
        result = progress.summarize(self.data, sha=self.sha)
        self.assertEqual(result["engineering_estimate_percent"], "22.69")
        self.assertEqual(result["accepted_scenarios"], 0)
        self.assertEqual(result["release_approved_packages"], 0)
        self.assertFalse(result["release_ready"])

    def test_all_26_packages_and_84_scenarios_are_required(self) -> None:
        for key in ("packages", "scenarios"):
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                data[key].pop()
                with self.assertRaises(ValueError):
                    progress.validate_register(data)

    def test_duplicates_cannot_inflate_progress(self) -> None:
        for key in ("packages", "scenarios"):
            data = copy.deepcopy(self.data)
            data[key][1] = copy.deepcopy(data[key][0])
            with self.assertRaises(ValueError):
                progress.validate_register(data)

    def test_malformed_ids_are_rejected(self) -> None:
        self.data["packages"][0]["id"] = []
        with self.assertRaises(ValueError):
            progress.validate_register(self.data)

    def test_bad_or_out_of_range_credits_are_rejected(self) -> None:
        for credit in ("NaN", "Infinity", "-0.1", "1.1", "bad", True, 0.5):
            with self.subTest(credit=credit):
                data = copy.deepcopy(self.data)
                data["packages"][0]["implementation_credit"] = credit
                with self.assertRaises(ValueError):
                    progress.validate_register(data)

    def test_full_credit_needs_approved_package(self) -> None:
        self.data["packages"][0]["implementation_credit"] = "1.00"
        with self.assertRaises(ValueError):
            progress.validate_register(self.data)

    def test_pass_needs_evidence_sha_and_environment(self) -> None:
        self.data["scenarios"][0]["status"] = "passed"
        for additions in ({}, {"evidence": ["report.xml"]}, {"evidence": ["report.xml"], "verified_sha": self.sha}):
            row = self.data["scenarios"][0]
            row.update(additions)
            with self.assertRaises(ValueError):
                progress.validate_register(self.data)

    def test_stale_evidence_is_not_current_acceptance(self) -> None:
        row = self.data["scenarios"][0]
        row.update(status="passed", evidence=["report.xml"], verified_sha=self.sha, environment="controlled-integration")
        self.assertEqual(progress.summarize(self.data, sha=self.sha)["accepted_scenarios"], 1)
        self.assertEqual(progress.summarize(self.data, sha="b" * 40)["accepted_scenarios"], 0)
        self.assertEqual(progress.summarize(self.data)["accepted_scenarios"], 0)

    def test_unknown_status_rejected(self) -> None:
        self.data["scenarios"][0]["status"] = "skipped-but-passed"
        with self.assertRaises(ValueError):
            progress.validate_register(self.data)

    def test_full_release_requires_every_exit_and_no_blocker(self) -> None:
        for row in self.data["packages"]:
            row.update(status="release-approved", implementation_credit="1.00", exit_evidence=["approval.json"], verified_sha=self.sha, environment="release")
        for row in self.data["scenarios"]:
            row.update(status="passed", evidence=["acceptance.xml"], verified_sha=self.sha, environment="release")
        self.assertFalse(progress.summarize(self.data, sha=self.sha)["release_ready"])
        self.data["release_blockers"] = []
        self.assertTrue(progress.summarize(self.data, sha=self.sha)["release_ready"])
        self.assertFalse(progress.summarize(self.data, sha="b" * 40)["release_ready"])

    def test_current_report_is_deterministic(self) -> None:
        expected = (progress.ROOT / "docs/production-implementation-progress.md").read_text()
        self.assertEqual(progress.render_markdown(self.data), expected)

    def test_require_release_returns_failure_for_incomplete_work(self) -> None:
        with patch.object(sys, "argv", [str(MODULE), "--sha", self.sha, "--require-release", "--json"]), redirect_stdout(StringIO()):
            self.assertEqual(progress.main(), 2)

    def test_stale_generated_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            report.write_text("outdated")
            with patch.object(sys, "argv", [str(MODULE), "--check", str(report)]), redirect_stderr(StringIO()):
                self.assertEqual(progress.main(), 1)

    def test_non_object_root_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            progress.validate_register([])


if __name__ == "__main__":
    unittest.main()
