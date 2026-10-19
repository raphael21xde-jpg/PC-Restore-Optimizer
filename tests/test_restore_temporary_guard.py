"""Safe restore staging: only disposable test-directory files are modified."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import backup_core
import backup_destination_guard
from backup_features import restore_selected, verified_entries
from multi_source_plan import prepare_multi_source_preview


class RestoreTemporaryGuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-restore-temp-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source_folder = self.root / 'source'
        source_folder.mkdir()
        self.source = source_folder / 'save.bin'
        self.payload = b'game-save-must-be-preserved'
        self.source.write_bytes(self.payload)
        self.backups = self.root / 'backups'
        self.backups.mkdir()
        self.restore_parent = self.root / 'restores'
        self.restore_parent.mkdir()
        plan = prepare_multi_source_preview(
            [str(self.source)], [str(source_folder)])
        folder, result = backup_core.copy_backup(
            plan, self.backups, strategy_inventory={})
        self.assertEqual(result['status'], 'concluido')
        self.manifest = folder / 'manifest.json'
        self.keys = list(verified_entries(self.manifest))

    def test_verified_copy_uses_protected_temporary_file(self):
        folder, count = restore_selected(
            self.manifest, self.keys, self.restore_parent,
            strategy_inventory={})
        self.assertEqual(count, 1)
        self.assertEqual(next(folder.rglob('save.bin')).read_bytes(), self.payload)
        self.assertFalse(list(folder.rglob('*.partial-*')))
        journal = json.loads(
            (folder / 'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'))
        self.assertEqual(journal['status'], 'concluida')

    def test_swapped_parent_during_temp_open_fails_closed(self):
        real_open = os.open
        swaps = []

        def swap_at_open(path, flags, *args, **kwargs):
            file = Path(path)
            if '.partial-' in file.name and not swaps:
                parent = file.parent
                retained = parent.with_name(parent.name + '-retained')
                parent.rename(retained)
                parent.mkdir()
                swaps.append((parent, retained))
            return real_open(path, flags, *args, **kwargs)

        with patch.object(
            backup_destination_guard.os, 'open', swap_at_open
        ):
            with self.assertRaises(OSError):
                restore_selected(
                    self.manifest, self.keys, self.restore_parent,
                    strategy_inventory={})

        self.assertEqual(len(swaps), 1, 'The ancestry swap must execute')
        journal = next(self.restore_parent.rglob('ESTADO-RESTAURACAO.json'))
        report = json.loads(journal.read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'falhou_parcial')
        self.assertEqual(report['verified'], 0)
        self.assertEqual(self.source.read_bytes(), self.payload)
        backup_file = next(self.manifest.parent.rglob('save.bin'))
        self.assertEqual(backup_file.read_bytes(), self.payload)


if __name__ == '__main__':
    unittest.main()
