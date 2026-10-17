"""Regression checks for cancellation/resume autotest #27.

All operations use temporary files; no real backups or volume operations.
"""
import threading
import unittest
from unittest.mock import patch

from autoteste_interrupcao import run_interruption_autotest


class TestAutotesteInterrupcao(unittest.TestCase):
    def test_backup_and_restore_cancel_resume_with_hashes(self):
        result = run_interruption_autotest()
        self.assertEqual(result["schema"], "pcro-autoteste-interrupcao-v1")
        self.assertEqual(result["status"], "aprovado")
        self.assertEqual(result["fixture_files"], 2)
        self.assertGreater(result["fixture_bytes"], 0)
        for key in (
            "backup_cancel_requested_during_operation",
            "backup_manifest_marked_interrupted",
            "incomplete_backup_rejected",
            "backup_resumed_and_sha256_verified",
            "restore_cancel_requested_during_operation",
            "restore_journal_marked_partial",
            "restore_resumed_and_sha256_verified",
            "no_backup_transfer_partials_left",
            "original_fixture_preserved",
            "temporary_data_cleaned",
        ):
            with self.subTest(key=key):
                self.assertTrue(result[key])
        self.assertEqual(result["backup_resume_count"], 1)
        self.assertEqual(result["restore_resume_count"], 1)
        for key in (
            "real_user_backups_accessed",
            "physical_independence_verified",
            "ready_for_format",
            "installation_authorized",
        ):
            with self.subTest(key=key):
                self.assertFalse(result[key])

    def test_pre_cancelled_request_does_not_create_fixtures(self):
        event = threading.Event()
        event.set()
        with self.assertRaisesRegex(InterruptedError, "usuário"):
            run_interruption_autotest(cancelled=event)

    def test_incorrect_acceptance_of_interrupted_backup_fails_closed(self):
        original = __import__("autoteste_interrupcao").verify_complete_manifest

        def broken(manifest, *, cancelled=None):
            import json
            from pathlib import Path
            doc = json.loads(Path(manifest).read_text(encoding="utf-8"))
            if doc.get("status") == "interrompido":
                return {"files_verified": 1}
            return original(manifest, cancelled=cancelled)

        with patch("autoteste_interrupcao.verify_complete_manifest", side_effect=broken):
            with self.assertRaisesRegex(AssertionError, "indevidamente aceito"):
                run_interruption_autotest()

    def test_restore_without_cancellation_is_not_approved(self):
        original = __import__("autoteste_interrupcao").restore_selected

        def broken(*args, **kwargs):
            # Simulate a defective restore engine which ignores the cancellation.
            kwargs.pop("cancelled", None)
            return original(*args, **kwargs)

        with patch("autoteste_interrupcao.restore_selected", side_effect=broken):
            with self.assertRaises(AssertionError):
                run_interruption_autotest()


if __name__ == "__main__":
    unittest.main()
