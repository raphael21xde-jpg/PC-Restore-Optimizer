"""Destination safety regression tests; only temporary fixture files."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_core
from backup_destination_guard import validate_backup_destination_path
from multi_source_plan import prepare_multi_source_preview
from transfer_engine import choose_strategy


class DestinationGuardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='pcro-dst-guard-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.src = self.base / 'source'
        self.dst = self.base / 'dest'
        self.src.mkdir()
        self.dst.mkdir()
        self.data = self.src / 'file.txt'
        self.data.write_bytes(b'preserve these bytes')

    def test_destination_inside_folder_allowed(self):
        target = self.dst / 'A' / 'file.txt'
        self.assertEqual(validate_backup_destination_path(self.dst, target), target)

    def test_escape_and_destination_root_rejected(self):
        for target in (self.base / 'outside.txt', self.dst):
            with self.subTest(target=str(target)), self.assertRaises(ValueError):
                validate_backup_destination_path(self.dst, target)

    def test_symlink_destination_ancestor_rejected_when_supported(self):
        other = self.base / 'elsewhere'
        other.mkdir()
        link = self.dst / 'junction'
        try:
            link.symlink_to(other, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest('Symlink creation unavailable: ' + str(error))
        with self.assertRaisesRegex(ValueError, 'Link ou junção'):
            validate_backup_destination_path(self.dst, link / 'file.txt')
        self.assertFalse((other / 'file.txt').exists())

    def test_copy_rechecks_destination_before_atomic_replace(self):
        plan = prepare_multi_source_preview([str(self.data)], [str(self.src)])
        import backup_destination_guard
        real_validate = backup_destination_guard.validate_backup_destination_path
        calls = []
        def guard(folder, target):
            calls.append(str(target))
            if len(calls) == 3:
                raise ValueError('Destino mudou durante a cópia')
            return real_validate(folder, target)
        with (patch.object(backup_destination_guard, 'validate_backup_destination_path', guard),
              patch.object(backup_core, 'choose_strategy',
                           lambda s, t, inventory=None: choose_strategy(s, t, inventory={}))):
            folder, report = backup_core.copy_backup(
                plan, self.dst,
                test_space_probe=lambda _p, _d: (100 * 1024**3, 10 * 1024**3, True))
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual(report['status'], 'parcial_com_erros')
        self.assertFalse(report['files'])
        self.assertFalse(any(folder.rglob('*.partial-*')))
        self.assertEqual(self.data.read_bytes(), b'preserve these bytes')


if __name__ == '__main__':
    unittest.main()
