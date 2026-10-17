"""Synthetic regression checks #31-34. No real backups or volumes are touched."""
import threading
import unittest
from unittest.mock import patch

from autotestes_falhas import (
    run_large_transfer_autotest,
    run_many_files_autotest,
    run_storage_fault_autotest,
    run_restart_recovery_autotest,
)


class TestBateria31a34(unittest.TestCase):
    def check_common(self, output, index):
        self.assertEqual(output["schema"], f"pcro-autoteste-falhas-v{index}")
        self.assertEqual(output["status"], "aprovado")
        self.assertTrue(output["temporary_data_cleaned"])
        for field in ("real_user_backups_accessed", "physical_independence_verified",
                      "ready_for_format", "installation_authorized"):
            self.assertFalse(output[field], field)

    def test_31_bounded_large_stream_sha256(self):
        report = run_large_transfer_autotest()
        self.check_common(report, 31)
        self.assertEqual(report["fixture_bytes"], 32 * 1024 * 1024)
        self.assertTrue(report["streamed_fixture_generation"])
        self.assertTrue(report["backup_sha256_verified"])
        self.assertTrue(report["restore_sha256_verified"])
        self.assertGreaterEqual(report["backup_elapsed_seconds"], 0)
        self.assertGreaterEqual(report["restore_elapsed_seconds"], 0)

    def test_32_many_tiny_files_sha256(self):
        report = run_many_files_autotest()
        self.check_common(report, 32)
        self.assertEqual(report["fixture_files"], 1024)
        self.assertEqual(report["groups"], 16)
        self.assertTrue(report["backup_sha256_verified"])
        self.assertTrue(report["restore_sha256_verified"])
        self.assertTrue(report["all_filenames_preserved"])

    def test_33_injected_faults_fail_closed(self):
        report = run_storage_fault_autotest()
        self.check_common(report, 33)
        for field in (
            "simulated_out_of_space_blocked",
            "simulated_read_failure_rejected",
            "simulated_write_failure_rejected",
            "failed_backups_marked_partial",
            "partial_fragments_cleaned",
            "simulated_restore_write_failure_journaled",
            "healthy_fixture_preserved",
        ):
            self.assertTrue(report[field], field)

    def test_34_interrupted_checkpoint_resume(self):
        report = run_restart_recovery_autotest()
        self.check_common(report, 34)
        for field in (
            "interrupted_checkpoint_rejected",
            "unrecorded_file_readopted_after_hash_verification",
            "missing_backup_file_recopied",
            "backup_resume_sha256_verified",
            "unfinished_restore_journal_recovered",
            "restore_resume_sha256_verified",
            "original_fixture_preserved",
        ):
            self.assertTrue(report[field], field)

    def test_cancel_before_start(self):
        for runner in (
            run_large_transfer_autotest, run_many_files_autotest,
            run_storage_fault_autotest, run_restart_recovery_autotest,
        ):
            with self.subTest(runner=runner.__name__):
                event = threading.Event()
                event.set()
                with self.assertRaises(InterruptedError):
                    runner(cancelled=event)

    def test_33_bad_disk_space_guard_does_not_approve(self):
        original = __import__("autotestes_falhas").copy_backup

        def wrong_engine(*args, **kwargs):
            if kwargs.get("test_space_probe"):
                raise ValueError("Falha fictícia por outra causa")
            return original(*args, **kwargs)

        with patch("autotestes_falhas.copy_backup", side_effect=wrong_engine):
            with self.assertRaises(ValueError):
                run_storage_fault_autotest()

    def test_34_partial_manifest_guard_must_reject(self):
        original = __import__("autotestes_falhas").verify_complete_manifest

        def broken(manifest, *, cancelled=None):
            import json
            from pathlib import Path
            if json.loads(Path(manifest).read_text(encoding="utf-8")).get("status") == "em_andamento":
                return {"files_verified": 1}
            return original(manifest, cancelled=cancelled)

        with patch("autotestes_falhas.verify_complete_manifest", side_effect=broken):
            with self.assertRaisesRegex(AssertionError, "aceito como íntegro"):
                run_restart_recovery_autotest()


if __name__ == "__main__":
    unittest.main()
