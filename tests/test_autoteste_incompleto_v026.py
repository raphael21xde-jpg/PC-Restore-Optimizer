"""Unit and fault-injection tests for synthetic backup failure autotest #26."""
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from autoteste_incompleto import run_incomplete_backup_autotest
from selective_recovery import verify_complete_manifest


class TestAutotesteBackupIncompleto(unittest.TestCase):
    def test_missing_partial_and_truncated_are_all_refused(self):
        result = run_incomplete_backup_autotest()
        self.assertEqual(result['status'], 'aprovado')
        self.assertEqual(result['scenarios'], 3)
        self.assertEqual(result['fixture_files'], 2)
        for key in (
            'healthy_manifest_verified',
            'copies_verified_before_faults',
            'missing_file_detected',
            'missing_file_restore_blocked',
            'partial_backup_detected',
            'partial_backup_restore_blocked',
            'truncated_manifest_detected',
            'truncated_manifest_restore_blocked',
            'restore_output_empty',
            'healthy_fixture_preserved',
            'temporary_data_cleaned',
        ):
            with self.subTest(key=key):
                self.assertTrue(result[key])
        for key in ('real_user_backups_accessed', 'ready_for_format',
                    'installation_authorized', 'physical_independence_verified'):
            self.assertFalse(result[key])
        self.assertIn('Arquivo de backup ausente',
                      result['missing_file_rejection']['verification_error'])
        self.assertIn('parcial',
                      result['partial_backup_rejection']['restoration_error'])
        self.assertIn('Número de arquivos',
                      result['truncated_manifest_rejection']['verification_error'])

    def test_cancel_before_creating_data(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            run_incomplete_backup_autotest(cancelled=cancelled)

    def test_defective_restore_guard_is_not_approved(self):
        with patch('autoteste_incompleto.run_isolated_restore_test',
                   return_value={'restore_verified': True}):
            with self.assertRaisesRegex(AssertionError, 'aceito indevidamente'):
                run_incomplete_backup_autotest()

    def test_defective_manifest_verifier_is_not_approved(self):
        def broken_verify(path, *, cancelled=None):
            if Path(path).parent.name == 'backup-arquivo-ausente':
                return {'files_verified': 2}
            return verify_complete_manifest(path, cancelled=cancelled)

        with patch('autoteste_incompleto.verify_complete_manifest',
                   side_effect=broken_verify):
            with self.assertRaisesRegex(AssertionError, 'aceito indevidamente'):
                run_incomplete_backup_autotest()


if __name__ == '__main__':
    unittest.main()
