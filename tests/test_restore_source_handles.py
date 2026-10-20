"""Restore source identity regressions using only disposable local fixtures.

Test races in the backup copy selected for restoration; no user files, real
volume operations, Windows installation, or format calls are performed.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import backup_core
import backup_source_guard
from backup_features import restore_selected, verified_entries
from multi_source_plan import prepare_multi_source_preview


class RestoreSourceHandleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-restore-source-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source_dir = self.root / 'original_source'
        source_dir.mkdir()
        self.original = source_dir / 'save.dat'
        self.payload = b'fixture-save-content'
        self.original.write_bytes(self.payload)
        backup_base = self.root / 'backups'
        backup_base.mkdir()
        self.restore_parent = self.root / 'restores'
        self.restore_parent.mkdir()
        plan = prepare_multi_source_preview(
            [str(self.original)], [str(source_dir)])
        backup_folder, report = backup_core.copy_backup(
            plan, backup_base, strategy_inventory={})
        self.assertEqual(report['status'], 'concluido')
        self.manifest = backup_folder / 'manifest.json'
        self.keys = list(verified_entries(self.manifest))
        self.backed_up = backup_folder / Path(self.keys[0])
        self.assertEqual(self.backed_up.read_bytes(), self.payload)

    def restore(self):
        return restore_selected(
            self.manifest, self.keys, self.restore_parent,
            strategy_inventory={})

    def assert_failed_without_output(self):
        folders = list(self.restore_parent.glob('TESTE-RESTAURACAO-v05-*'))
        self.assertEqual(len(folders), 1)
        folder = folders[0]
        journal = json.loads(
            (folder / 'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'))
        self.assertEqual(journal['status'], 'falhou_parcial')
        self.assertEqual(journal['verified'], 0)
        self.assertFalse(list(folder.rglob('save.dat')))
        self.assertEqual(self.original.read_bytes(), self.payload)

    def test_restore_normal_source_still_passes(self):
        folder, count = self.restore()
        self.assertEqual(count, 1)
        self.assertEqual(next(folder.rglob('save.dat')).read_bytes(), self.payload)

    def test_source_replaced_at_open_even_with_identical_bytes_and_mtime(self):
        before = self.backed_up.stat()
        replacement = self.backed_up.with_name('replacement.dat')
        replacement.write_bytes(self.payload)
        os.utime(
            replacement,
            ns=(before.st_atime_ns, before.st_mtime_ns))
        retained = self.backed_up.with_name('retained-original.dat')
        original_open = os.open
        swaps = []

        def swap_at_open(path, flags, *args, **kwargs):
            if Path(path) == self.backed_up and not swaps:
                self.backed_up.rename(retained)
                replacement.rename(self.backed_up)
                swaps.append(True)
            return original_open(path, flags, *args, **kwargs)

        with patch.object(backup_source_guard.os, 'open', swap_at_open):
            with self.assertRaises(OSError):
                self.restore()
        self.assertTrue(swaps, 'The backup source swap must execute')
        self.assertEqual(retained.read_bytes(), self.payload)
        self.assertEqual(self.backed_up.read_bytes(), self.payload)
        self.assert_failed_without_output()

    def test_source_parent_replaced_while_preserving_file_identity(self):
        before = self.backed_up.stat()
        source_parent = self.backed_up.parent
        retained_parent = source_parent.with_name(
            source_parent.name + '-retained')
        original_open = os.open
        swaps = []

        def swap_parent_at_open(path, flags, *args, **kwargs):
            if Path(path) == self.backed_up and not swaps:
                source_parent.rename(retained_parent)
                source_parent.mkdir()
                (retained_parent / self.backed_up.name).rename(self.backed_up)
                swaps.append(True)
            return original_open(path, flags, *args, **kwargs)

        with patch.object(backup_source_guard.os, 'open', swap_parent_at_open):
            with self.assertRaises(OSError):
                self.restore()
        self.assertTrue(swaps, 'The backup source ancestor swap must execute')
        after = self.backed_up.stat()
        self.assertEqual((after.st_dev, after.st_ino),
                         (before.st_dev, before.st_ino))
        self.assertEqual(self.backed_up.read_bytes(), self.payload)
        self.assert_failed_without_output()


if __name__ == '__main__':
    unittest.main()
