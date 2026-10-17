"""Regression tests for self-contained SHA-256 fault-injection autotest."""
import threading
import unittest
from unittest.mock import patch

from autoteste_integridade import run_integrity_autotest


class TestAutotesteIntegridade(unittest.TestCase):
    def test_detects_corruption_and_blocks_restore(self):
        outcome = run_integrity_autotest()
        self.assertEqual(outcome['status'], 'aprovado')
        self.assertEqual(outcome['fixture_files'], 2)
        self.assertTrue(outcome['sha256_mismatch_detected'])
        self.assertTrue(outcome['unsafe_restore_blocked'])
        self.assertTrue(outcome['restore_output_empty'])
        self.assertTrue(outcome['healthy_fixture_preserved'])
        self.assertTrue(outcome['temporary_data_cleaned'])
        self.assertFalse(outcome['real_user_backups_accessed'])
        self.assertFalse(outcome['ready_for_format'])
        self.assertIn('SHA-256 divergente', outcome['verify_rejection'])
        self.assertIn('SHA-256 divergente', outcome['restore_rejection'])

    def test_cancellation_before_start(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            run_integrity_autotest(cancelled=cancel)

    def test_unexpected_restore_acceptance_is_not_reported_as_success(self):
        with patch('autoteste_integridade.run_isolated_restore_test', return_value={
            'restore_verified': True,
        }):
            with self.assertRaisesRegex(AssertionError, 'aceito indevidamente'):
                run_integrity_autotest()


if __name__ == '__main__':
    unittest.main()
