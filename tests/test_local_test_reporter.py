"""Local-only regression tests for the optional PR test-report tool.

These tests never invoke GitHub or upload real log content.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "test_reporter.py"
SPEC = importlib.util.spec_from_file_location("pcro_test_reporter", SCRIPT)
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)


class LocalTestReporterTests(unittest.TestCase):
    def test_sensitive_windows_user_path_and_email_are_redacted(self):
        value = ("C:\\Users\\someone\\AppData\\Local\\Temp "
                 "alice@example.org ghp_abcdefghijklmnopqrstuvwxyz123456 "
                 "password=do-not-share")
        cleaned = reporter.sanitize_for_public_comment(
            value, home=Path("C:/not-this-home"))
        for secret in ("someone", "alice@example.org",
                       "ghp_abcdefghijklmnopqrstuvwxyz123456", "do-not-share"):
            self.assertNotIn(secret, cleaned)
        self.assertIn("[USER_HOME]", cleaned)

    def test_unittest_summary_includes_skips_and_failure(self):
        log = "test_x ... ok\n\nRan 3 tests in 1.2s\n\nOK (skipped=1)\n"
        self.assertIn("Ran 3 tests", reporter.result_summary(log))
        self.assertIn("OK (skipped=1)", reporter.result_summary(log))
        failed = "Ran 2 tests in 0.3s\n\nFAILED (failures=1)"
        self.assertIn("FAILED (failures=1)", reporter.result_summary(failed))

    def test_public_comment_uses_redacted_log_and_revision(self):
        raw = "test_x ... ok\nC:\\Users\\someone\\private\n\nRan 1 test in 0.2s\n\nOK"
        body = reporter.report_comment(
            raw, pattern="test_local_test_reporter.py", exit_code=0,
            sha="abc123", date_utc="2026-10-18 UTC")
        self.assertIn("abc123", body)
        self.assertIn("PASSOU", body)
        self.assertIn("Ran 1 test", body)
        self.assertNotIn("someone", body)

    def test_no_network_without_explicit_publish_flag(self):
        with tempfile.TemporaryDirectory() as root:
            reports = Path(root)
            def fake_tests(pattern, path):
                path.write_text("Ran 1 test in 0.001s\n\nOK\n", encoding="utf-8")
                return 0
            with (patch.object(reporter, "REPORT_DIR", reports),
                  patch.object(reporter, "run_unittest", side_effect=fake_tests),
                  patch.object(reporter, "git_commit", return_value="abc123"),
                  patch.object(reporter, "publish_comment") as publishing):
                self.assertEqual(
                    reporter.main(["--pattern", "test_local_test_reporter.py"]), 0)
            publishing.assert_not_called()
            self.assertEqual(len(list(reports.glob("*.log"))), 1)
            self.assertEqual(len(list(reports.glob("*.md"))), 1)

    def test_publish_requires_gh_cli(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.md"
            path.write_text("fixture", encoding="utf-8")
            with patch.object(reporter.shutil, "which", return_value=None):
                self.assertFalse(reporter.publish_comment(
                    path, "example/project", 54))

    def test_publish_uses_explicit_pr_and_body_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.md"
            path.write_text("fixture", encoding="utf-8")
            with (patch.object(reporter.shutil, "which", return_value="gh"),
                  patch.object(reporter.subprocess, "run",
                               return_value=SimpleNamespace(
                                   returncode=0, stdout="", stderr="")) as runner):
                self.assertTrue(reporter.publish_comment(
                    path, "example/project", 54))
            args = runner.call_args.args[0]
            self.assertEqual(
                args, ["gh", "pr", "comment", "54", "--repo",
                       "example/project", "--body-file", str(path)])


if __name__ == "__main__":
    unittest.main()
