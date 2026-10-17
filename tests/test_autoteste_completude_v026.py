"""Safe regressions for synthetic missing-file and incomplete-backup autotest."""
import threading
import unittest
from unittest.mock import patch

from autoteste_completude import run_completeness_autotest


class TestAutotesteCompletude(unittest.TestCase):
    def test_all_incomplete_scenarios_block_restore(self):
        result = run_completeness_autotest()
        self.assertEqual(result["status"], "aprovado")
        self.assertEqual(result["fixture_files"], 2)
        self.assertTrue(result["healthy_manifest_verified"])
        self.assertTrue(result["missing_file_detected"])
        self.assertTrue(result["interrupted_backup_rejected"])
        self.assertTrue(result["incomplete_manifest_rejected"])
        self.assertTrue(result["unsafe_restores_blocked"])
        self.assertTrue(result["restore_outputs_empty"])
        self.assertTrue(result["healthy_fixture_preserved"])
        self.assertTrue(result["temporary_data_cleaned"])
        self.assertFalse(result["real_user_backups_accessed"])
        self.assertFalse(result["ready_for_format"])
        self.assertFalse(result["installation_authorized"])
        self.assertEqual(
            set(result["scenarios"]),
            {"missing_file", "interrupted_manifest", "missing_entry"},
        )
        for scenario in result["scenarios"].values():
            self.assertTrue(scenario["restore_blocked"])
            self.assertTrue(scenario["verification_rejected"])
            self.assertTrue(scenario["restore_output_empty"])

    def test_cancellation_before_file_generation(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(InterruptedError):
            run_completeness_autotest(cancelled=stop)

    def test_rejects_a_verifier_that_accepts_missing_data(self):
        original_verify = __import__("autoteste_completude").verify_complete_manifest

        def broken_verify(path, *, cancelled=None):
            try:
                return original_verify(path, cancelled=cancelled)
            except OSError as error:
                if "SHA-256 divergente" in str(error):
                    return {"files_verified": 2, "backup_verified": True}
                raise

        with patch("autoteste_completude.verify_complete_manifest", side_effect=broken_verify):
            with self.assertRaisesRegex(AssertionError, "aceito indevidamente"):
                run_completeness_autotest()

    def test_rejects_a_restore_guard_that_accepts_missing_data(self):
        with patch(
            "autoteste_completude.run_isolated_restore_test",
            return_value={"restore_verified": True},
        ):
            with self.assertRaisesRegex(AssertionError, "aceito indevidamente"):
                run_completeness_autotest()

    def test_rejects_a_wrong_failure_reason(self):
        with patch(
            "autoteste_completude.run_isolated_restore_test",
            side_effect=ValueError("Erro genérico, não uma proteção de backup incompleto"),
        ):
            with self.assertRaisesRegex(AssertionError, "motivo errado"):
                run_completeness_autotest()


if __name__ == "__main__":
    unittest.main()
