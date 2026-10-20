"""Reopen backups without the original inventory, using only test fixtures."""
import json
from pathlib import Path
import tempfile
import unittest

from test_multi_source_recovery_center import _FixtureBase
from multi_source_offline_import import reopen_fixture_backup_session
from multi_source_recovery_center import inspect_fixture_recovery
from multi_source_fixture_restore import recover_from_fixture_copies


class OfflineBackupImportTests(_FixtureBase, unittest.TestCase):
    def reopen(self, roots=None, destination=None):
        return reopen_fixture_backup_session(
            [str(self.t), str(self.u)] if roots is None else roots,
            str(self.restore_parent) if destination is None else destination,
            test_root=str(self.root))

    def inspect(self, session):
        return inspect_fixture_recovery(
            session['plan'], session['copies_report'],
            session['restore_parent'], test_root=str(self.root))

    def recover(self, session, keys=None):
        keys = keys or [task.destination for task in session['plan'].files]
        return recover_from_fixture_copies(
            session['plan'], session['copies_report'],
            keys, session['restore_parent'], test_root=str(self.root))

    def remove_origins(self):
        self.first.unlink()
        self.second.unlink()

    def assert_empty_recovery(self):
        self.assertEqual(list(self.restore_parent.iterdir()), [])

    def test_rebuild_from_two_manifests_without_original_plan_or_files(self):
        self.remove_origins()
        session = self.reopen()
        self.assertTrue(session['offline_mode'])
        self.assertFalse(session['original_sources_required'])
        self.assertFalse(session['backup_verified'])
        self.assertEqual(session['copies_report']['copies_verified_locally'], 0)
        self.assertEqual(session['plan'].count, 2)
        self.assertFalse(any(Path(t.source).exists()
                             for t in session['plan'].files))
        inspected = self.inspect(session)
        self.assertEqual(inspected['copies_verified'], 2)
        self.assertTrue(inspected['can_restore_in_fixture'])
        report = self.recover(session)
        self.assertEqual(report['status'], 'restored_verified')
        self.assertEqual(report['files_restored'], 2)
        self.assertFalse(report['ready_for_format'])
        self.assertFalse(report['installation_authorized'])
        restored = Path(report['restored_folder'])
        self.assertEqual(next(restored.rglob('document.txt')).read_bytes(),
                         b'keep-first')
        self.assertEqual(next(restored.rglob('game.sav')).read_bytes(),
                         b'keep-second')
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())

    def test_restore_explicit_selection_only(self):
        session = self.reopen()
        key = next(t.destination for t in session['plan'].files
                   if t.destination.endswith('document.txt'))
        report = self.recover(session, [key])
        self.assertTrue(report['restore_verified'])
        self.assertEqual(report['files_restored'], 1)
        target = Path(report['restored_folder'])
        self.assertEqual(next(target.rglob('document.txt')).read_bytes(),
                         b'keep-first')
        self.assertFalse(list(target.rglob('game.sav')))
        self.assertEqual(self.first.read_bytes(), b'keep-first')
        self.assertEqual(self.second.read_bytes(), b'keep-second')

    def test_corrupt_first_copy_falls_back_after_offline_reopen(self):
        first_backup = Path(self.copies['destinations'][0]['manifest'])
        next(first_backup.parent.rglob('document.txt')).write_bytes(b'bad')
        self.remove_origins()
        session = self.reopen()
        inspected = self.inspect(session)
        self.assertEqual(inspected['suggested_copy_index'], 2)
        self.assertEqual(inspected['copies'][0]['status'], 'integrity_failed')
        outcome = self.recover(session)
        self.assertEqual(outcome['status'], 'restored_verified')
        self.assertEqual(outcome['chosen_copy_index'], 2)
        self.assertEqual(outcome['files_restored'], 2)

    def test_missing_first_manifest_uses_second(self):
        first = Path(self.copies['destinations'][0]['manifest'])
        first.unlink()
        session = self.reopen()
        inspected = self.inspect(session)
        self.assertEqual(inspected['copies'][0]['status'], 'manifest_missing')
        self.assertEqual(inspected['suggested_copy_index'], 2)
        recovered = self.recover(session)
        self.assertTrue(recovered['restore_verified'])
        self.assertEqual(recovered['chosen_copy_index'], 2)

    def test_different_inventory_hashes_block_without_writes(self):
        first = Path(self.copies['destinations'][0]['manifest'])
        doc = json.loads(first.read_text(encoding='utf-8'))
        doc['files'][0]['sha256'] = 'f' * 64
        first.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'diferentes'):
            self.reopen()
        self.assert_empty_recovery()

    def test_different_backup_job_fingerprints_block(self):
        first = Path(self.copies['destinations'][0]['manifest'])
        doc = json.loads(first.read_text(encoding='utf-8'))
        doc['plan_fingerprint'] = '0' * 64
        first.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'diferentes'):
            self.reopen()
        self.assert_empty_recovery()

    def test_ambiguous_multiple_backups_in_one_folder_refused(self):
        (self.t / 'backup-second-job').mkdir()
        with self.assertRaisesRegex(ValueError, 'Mais de um backup'):
            self.reopen()
        self.assert_empty_recovery()

    def test_both_manifests_missing_fail_closed(self):
        for record in self.copies['destinations']:
            Path(record['manifest']).unlink()
        with self.assertRaisesRegex(ValueError, 'Nenhum manifesto'):
            self.reopen()
        self.assert_empty_recovery()

    def test_bad_first_manifest_can_be_bypassed_with_complete_second(self):
        first = Path(self.copies['destinations'][0]['manifest'])
        first.write_text('{"incompleto": true}', encoding='utf-8')
        session = self.reopen()
        inspected = self.inspect(session)
        self.assertEqual(inspected['copies'][0]['status'], 'manifest_invalid')
        self.assertEqual(inspected['copies_verified'], 1)
        result = self.recover(session)
        self.assertTrue(result['restore_verified'])
        self.assertEqual(result['chosen_copy_index'], 2)

    def test_non_sandbox_roots_and_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix='pcro-other-root-') as outside:
            with self.assertRaisesRegex(ValueError, 'fora da raiz'):
                self.reopen(roots=[outside, str(self.u)])
            with self.assertRaisesRegex(ValueError, 'fora da raiz'):
                self.reopen(destination=outside)
        self.assert_empty_recovery()

    def test_import_does_not_claim_verified_copies_or_format_readiness(self):
        session = self.reopen()
        self.assertFalse(session['backup_verified'])
        self.assertFalse(session['restore_verified'])
        self.assertFalse(session['ready_for_format'])
        self.assertFalse(session['installation_authorized'])
        self.assertFalse(session['copies_report']['installation_authorized'])
        self.assertFalse(session['copies_report']['physical_independence_verified'])
        self.assert_empty_recovery()


if __name__ == '__main__':
    unittest.main()
