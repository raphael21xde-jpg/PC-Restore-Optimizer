"""Smart restore regressions using only private temporary fixture files.

No writes to real user disks, no formatting, and no production UI integration.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import backup_core
from multi_source_fixture_runner import run_multi_source_fixture_backups
from multi_source_fixture_restore import recover_from_fixture_copies
from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from transfer_engine import choose_strategy


class SmartRestoreFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcro-smart-restore-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sources = [self.root / 'source_A', self.root / 'source_B']
        self.targets = [self.root / 'backup_T', self.root / 'backup_U']
        self.restore_parent = self.root / 'restored'
        for folder in [*self.sources, *self.targets, self.restore_parent]:
            folder.mkdir()
        self.source_a = self.sources[0] / 'document.txt'
        self.source_b = self.sources[1] / 'game.sav'
        self.source_a.write_bytes(b'important-document')
        self.source_b.write_bytes(b'important-game-save')
        self.expected = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (self.source_a, self.source_b)
        }
        self.plan = prepare_multi_source_preview(
            [str(self.source_a), str(self.source_b)],
            [str(p) for p in self.sources])
        self.preview = preview_multi_source_targets(
            self.plan, [str(p) for p in self.targets],
            volume_lookup=self.volume, usage=self.usage)
        with patch.object(
            backup_core, 'choose_strategy',
            lambda a, b, inventory=None: choose_strategy(a, b, inventory={})
        ):
            self.copies = run_multi_source_fixture_backups(
                self.plan, self.preview, test_root=str(self.root),
                volume_lookup=self.volume, usage=self.usage)
        self.assertEqual(self.copies['status'], 'all_local_copies_verified')
        self.keys = [task.destination for task in self.plan.files]

    def volume(self, raw):
        path = Path(raw)
        for folder, drive in (
            (self.sources[0], 'A:'), (self.sources[1], 'B:'),
            (self.targets[0], 'T:'), (self.targets[1], 'U:')
        ):
            if path == folder or folder in path.parents:
                return drive
        return 'SEM UNIDADE'

    @staticmethod
    def usage(_):
        return SimpleNamespace(free=100 * 1024 ** 3)

    def recover(self, keys=None, copies=None, restore_parent=None):
        return recover_from_fixture_copies(
            self.plan, self.copies if copies is None else copies,
            self.keys if keys is None else keys,
            self.restore_parent if restore_parent is None else restore_parent,
            test_root=str(self.root))

    def assert_sources_untouched(self):
        self.assertEqual(
            {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (self.source_a, self.source_b)},
            self.expected)

    def assert_no_restoration(self):
        self.assertFalse(
            list(self.restore_parent.glob('TESTE-RESTAURACAO-v05-*')))

    def test_healthy_copy_recovers_only_selected_file(self):
        document_key = next(key for key in self.keys if key.endswith('document.txt'))
        report = self.recover(keys=[document_key])
        self.assertEqual(report['status'], 'restored_verified')
        self.assertEqual(report['chosen_copy_index'], 1)
        self.assertEqual(report['files_restored'], 1)
        self.assertTrue(report['restore_verified'])
        self.assertFalse(report['ready_for_format'])
        self.assertFalse(report['physical_independence_verified'])
        restored = Path(report['restored_folder'])
        found = list(restored.rglob('document.txt'))
        self.assertEqual(len(found), 1)
        self.assertEqual(
            hashlib.sha256(found[0].read_bytes()).hexdigest(),
            self.expected['document.txt'])
        self.assertFalse(list(restored.rglob('game.sav')))
        self.assert_sources_untouched()

    def test_corrupt_first_copy_uses_second_whole_copy(self):
        first = Path(self.copies['destinations'][0]['manifest'])
        (next(first.parent.rglob('document.txt'))).write_bytes(b'corrupted')
        report = self.recover()
        self.assertEqual(report['status'], 'restored_verified')
        self.assertEqual(report['chosen_copy_index'], 2)
        self.assertEqual(report['copy_checks'][0]['status'], 'integrity_failed')
        self.assertEqual(report['copy_checks'][1]['status'], 'selected_for_restore')
        self.assertEqual(report['files_restored'], 2)
        restored = Path(report['restored_folder'])
        found = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in restored.rglob('*')
                 if p.is_file() and p.name in self.expected}
        self.assertEqual(found, self.expected)
        self.assert_sources_untouched()

    def test_both_corrupt_stops_without_restoring(self):
        for row in self.copies['destinations']:
            manifest = Path(row['manifest'])
            next(manifest.parent.rglob('document.txt')).write_bytes(b'bad')
        report = self.recover()
        self.assertEqual(report['status'], 'no_usable_copy')
        self.assertFalse(report['backup_verified'])
        self.assertFalse(report['restore_verified'])
        self.assertFalse(report['installation_authorized'])
        self.assert_no_restoration()
        self.assert_sources_untouched()

    def test_conflicting_manifest_hashes_block_all_restoration(self):
        path = Path(self.copies['destinations'][0]['manifest'])
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc['files'][0]['sha256'] = 'f' * 64
        path.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'divergem'):
            self.recover()
        self.assert_no_restoration()

    def test_destination_cannot_be_outside_or_inside_a_backup(self):
        with tempfile.TemporaryDirectory(prefix='pcro-outside-recovery-') as tmp:
            with self.assertRaisesRegex(ValueError, 'fora da raiz'):
                self.recover(restore_parent=tmp)
        with self.assertRaisesRegex(ValueError, 'sobrepostos'):
            self.recover(restore_parent=str(self.targets[0]))
        self.assert_no_restoration()

    def test_forged_manifest_path_is_rejected_without_writes(self):
        rows = [dict(x) for x in self.copies['destinations']]
        rows[0]['manifest'] = rows[1]['manifest']
        forged = dict(self.copies, destinations=rows)
        with self.assertRaisesRegex(ValueError, 'Manifesto fora'):
            self.recover(copies=forged)
        self.assert_no_restoration()

    def test_restoration_does_not_require_original_source_to_still_exist(self):
        self.source_a.unlink()
        self.source_b.unlink()
        report = self.recover()
        self.assertEqual(report['status'], 'restored_verified')
        self.assertEqual(report['files_restored'], 2)
        recovered = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in Path(report['restored_folder']).rglob('*')
                     if p.is_file() and p.name in self.expected}
        self.assertEqual(recovered, self.expected)

    def test_rejects_unselected_or_unsafe_file(self):
        with self.assertRaisesRegex(ValueError, 'não pertence ao plano'):
            self.recover(keys=['C/unknown.exe'])
        with self.assertRaises(ValueError):
            self.recover(keys=['../escape'])
        self.assert_no_restoration()


if __name__ == '__main__':
    unittest.main()
