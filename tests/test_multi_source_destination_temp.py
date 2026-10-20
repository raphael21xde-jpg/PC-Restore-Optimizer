"""Destination temporary handle safeguards using only disposable fixtures."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_core
import backup_destination_guard
from backup_destination_guard import (
    destination_ancestry_identity, open_verified_backup_temp,
    safe_cleanup_backup_temp,
)
from multi_source_plan import prepare_multi_source_preview
from transfer_engine import choose_strategy


class MultiSourceDestinationTempTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='pcro-temp-identity-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.backup = self.root / 'backup'
        self.backup.mkdir()
        self.source_root = self.root / 'source'
        self.source_root.mkdir()
        self.source = self.source_root / 'data.bin'
        self.source.write_bytes(b'original source')
        self.parent = self.backup / 'nested'
        self.parent.mkdir()
        self.destination = self.parent / 'copy.bin'
        self.partial = self.parent / 'copy.bin.partial-test'
        self.snapshot = destination_ancestry_identity(self.backup, self.destination)

    def test_new_private_temp_handle_can_be_verified(self):
        with open_verified_backup_temp(
            self.backup, self.destination, self.partial, self.snapshot
        ) as handle:
            handle.write(b'fixture payload')
        self.assertEqual(self.partial.read_bytes(), b'fixture payload')
        self.assertFalse(self.destination.exists())

    def test_cleanup_never_unlinks_in_swapped_directory(self):
        moved = self.backup / 'original-nested'
        self.parent.rename(moved)
        self.parent.mkdir()
        self.partial.write_bytes(b'other directory data')
        safe_cleanup_backup_temp(
            self.backup, self.destination, self.partial, self.snapshot)
        self.assertEqual(self.partial.read_bytes(), b'other directory data')

    def test_mismatched_open_handle_is_rejected(self):
        unrelated = self.root / 'unrelated.bin'
        unrelated.write_bytes(b'keep me')
        real_open = os.open

        def wrong_handle(path, flags, *args, **kwargs):
            if Path(path) == self.partial:
                return real_open(unrelated, os.O_WRONLY)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(backup_destination_guard.os, 'open', wrong_handle):
            with self.assertRaises(OSError):
                with open_verified_backup_temp(
                    self.backup, self.destination, self.partial, self.snapshot
                ) as handle:
                    handle.write(b'unsafe')
        self.assertEqual(unrelated.read_bytes(), b'keep me')
        self.assertFalse(self.partial.exists())

    def test_backup_refuses_renamed_destination_parent_at_temp_creation(self):
        plan = prepare_multi_source_preview(
            [str(self.source)], [str(self.source_root)])
        real_open = os.open
        changed = [False]

        def swap_on_temp_open(path, flags, *args, **kwargs):
            if ('.partial-' in str(path) and not changed[0]
                    and os.path.basename(str(path)).startswith('data.bin.partial-')):
                changed[0] = True
                parent = Path(path).parent
                original = parent.with_name(parent.name + '-old')
                parent.rename(original)
                parent.mkdir()
            return real_open(path, flags, *args, **kwargs)

        with (patch.object(backup_destination_guard.os, 'open', swap_on_temp_open),
              patch.object(backup_core, 'choose_strategy',
                           lambda a, b, inventory=None: choose_strategy(a, b, inventory={}))):
            folder, result = backup_core.copy_backup(
                plan, self.backup,
                test_space_probe=lambda p, d: (100 * 1024**3, 10 * 1024**3, True))
        self.assertTrue(changed[0])
        self.assertEqual(result['status'], 'parcial_com_erros')
        self.assertFalse(result['files'])
        self.assertEqual(self.source.read_bytes(), b'original source')


if __name__ == '__main__':
    unittest.main()
