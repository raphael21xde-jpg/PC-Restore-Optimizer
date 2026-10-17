"""Cross-platform regression tests for synthetic resilience checks #28–#30."""
import threading
import unittest
from unittest.mock import patch

from autotestes_resiliencia import (
    run_midfile_autotest,
    run_repair_autotest,
    run_resume_guard_autotest,
)


class TestResiliencia(unittest.TestCase):
    def test_28_midfile_cancellation_and_verified_resume(self):
        report = run_midfile_autotest()
        self.assertEqual(report["status"], "aprovado")
        self.assertEqual(report["schema"], "pcro-autoteste-resiliencia-v28")
        self.assertGreater(report["fixture_bytes"], 3 * 1024 * 1024)
        for field in (
            "midfile_backup_cancelled",
            "incomplete_file_not_marked_verified",
            "interrupted_backup_rejected",
            "partial_backup_fragment_removed",
            "backup_resume_sha256_verified",
            "midfile_restore_cancelled",
            "incomplete_restore_not_marked_verified",
            "partial_restore_fragment_removed",
            "restore_resume_sha256_verified",
            "original_fixture_preserved",
            "temporary_data_cleaned",
        ):
            with self.subTest(field=field):
                self.assertTrue(report[field])
        self.assertIn("Backup parcial", report["interruption_rejection"])
        self.assertFalse(report["real_user_backups_accessed"])
        self.assertFalse(report["ready_for_format"])
        self.assertFalse(report["installation_authorized"])

    def test_29_corrupted_backup_and_restore_are_repaired(self):
        report = run_repair_autotest()
        self.assertEqual(report["status"], "aprovado")
        self.assertEqual(report["schema"], "pcro-autoteste-resiliencia-v29")
        for field in (
            "backup_cancelled_and_refused",
            "corrupted_verified_backup_file_replaced",
            "backup_resume_sha256_verified",
            "restore_cancelled_and_journaled",
            "corrupted_restored_file_replaced",
            "restore_resume_sha256_verified",
            "original_fixture_preserved",
            "temporary_data_cleaned",
        ):
            with self.subTest(field=field):
                self.assertTrue(report[field])
        self.assertFalse(report["real_user_backups_accessed"])
        self.assertFalse(report["ready_for_format"])
        self.assertFalse(report["installation_authorized"])

    def test_30_resume_guards_reject_changed_or_mismatched_state(self):
        report = run_resume_guard_autotest()
        self.assertEqual(report["status"], "aprovado")
        self.assertEqual(report["schema"], "pcro-autoteste-resiliencia-v30")
        for field in (
            "source_change_blocks_backup_resume",
            "different_backup_base_blocks_resume",
            "interrupted_backup_still_unapproved",
            "different_restore_base_blocks_resume",
            "different_manifest_blocks_restore_resume",
            "rejected_resume_did_not_change_journal",
            "temporary_data_cleaned",
        ):
            with self.subTest(field=field):
                self.assertTrue(report[field])
        self.assertFalse(report["real_data_changed"])
        self.assertFalse(report["real_user_backups_accessed"])
        self.assertFalse(report["ready_for_format"])
        self.assertFalse(report["installation_authorized"])

    def test_cancel_before_any_operation(self):
        for runner in (run_midfile_autotest, run_repair_autotest,
                       run_resume_guard_autotest):
            with self.subTest(runner=runner.__name__):
                stop = threading.Event()
                stop.set()
                with self.assertRaises(InterruptedError):
                    runner(cancelled=stop)

    def test_28_refuses_defective_complete_manifest_guard(self):
        original = __import__("autotestes_resiliencia").verify_complete_manifest

        def broken(path, *, cancelled=None):
            import json
            from pathlib import Path
            manifest = json.loads(Path(path).read_text(encoding="utf-8"))
            if manifest.get("status") == "interrompido":
                return {"files_verified": 0}
            return original(path, cancelled=cancelled)

        with patch("autotestes_resiliencia.verify_complete_manifest",
                   side_effect=broken):
            with self.assertRaisesRegex(AssertionError, "indevidamente"):
                run_midfile_autotest()

    def test_30_rejects_broken_destination_guard(self):
        original = __import__("autotestes_resiliencia").copy_backup

        def allow_other_base(*args, **kwargs):
            from pathlib import Path
            # This replacement deliberately spoils the foreign-base rejection.
            if "resume_manifest" in kwargs and (
                Path(args[1]).name == "destino-estranho-ficticio"
            ):
                return Path(kwargs["resume_manifest"]).parent, {"status": "concluido"}
            return original(*args, **kwargs)

        with patch("autotestes_resiliencia.copy_backup", side_effect=allow_other_base):
            with self.assertRaisesRegex(AssertionError, "proteção não recusou"):
                run_resume_guard_autotest()


if __name__ == "__main__":
    unittest.main()
