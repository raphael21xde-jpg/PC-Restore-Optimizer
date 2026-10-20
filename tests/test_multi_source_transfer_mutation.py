"""Regression tests for files changing while backup_core copies synthetic data.

No real user sources, disks, installation or formatting are touched.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_core
from multi_source_plan import prepare_multi_source_preview
from transfer_engine import choose_strategy


class MultiSourceTransferMutationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-transfer-mutation-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.source_dir = self.base / 'source'
        self.target = self.base / 'target'
        self.source_dir.mkdir()
        self.target.mkdir()
        self.source = self.source_dir / 'sample.dat'
        self.source.write_bytes(b'original-data')
        self.plan = prepare_multi_source_preview(
            [str(self.source)], [str(self.source_dir)])

    def _copy(self, hook=None):
        with patch.object(backup_core, 'choose_strategy',
                          lambda s, t, inventory=None:
                          choose_strategy(s, t, inventory={})):
            return backup_core.copy_backup(
                self.plan, self.target, test_fault_hook=hook,
                test_space_probe=lambda plan, target: (100 * 1024**3, 10 * 1024**3, True))

    def test_unchanged_source_is_verified(self):
        folder, report = self._copy()
        self.assertEqual(report['status'], 'concluido')
        self.assertEqual(report['file_count_expected'], 1)
        self.assertEqual(len(report['files']), 1)
        self.assertTrue((folder / 'manifest.json').is_file())
        self.assertEqual(self.source.read_bytes(), b'original-data')

    def test_source_changed_during_copy_is_not_verified(self):
        changed = [False]
        def hook(stage):
            if stage == 'backup_after_write' and not changed[0]:
                changed[0] = True
                self.source.write_bytes(b'altered-data-longer')
        folder, report = self._copy(hook)
        self.assertTrue(changed[0])
        self.assertEqual(report['status'], 'parcial_com_erros')
        self.assertFalse(report['files'])
        self.assertTrue(report['errors'])
        self.assertFalse(any(folder.rglob('*.partial-*')))


if __name__ == '__main__':
    unittest.main()
