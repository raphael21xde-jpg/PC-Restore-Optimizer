"""Synthetic source handle identity and pre-open race tests.

Runs only in private temporary folders; does not modify real disks.
"""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_core
import backup_source_guard
from backup_source_guard import (
    open_verified_backup_source, sha256_verified_backup_source)
from multi_source_plan import prepare_multi_source_preview
from transfer_engine import choose_strategy


class MultiSourceSourceHandleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-source-handle-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root / 'source'
        self.dst = self.root / 'destination'
        self.src.mkdir()
        self.dst.mkdir()
        self.file = self.src / 'data.bin'
        self.file.write_bytes(b'original-content')
        self.metadata = self.file.stat()

    def test_regular_file_is_bound_and_hashed(self):
        with open_verified_backup_source(
            self.file, self.metadata.st_size, self.metadata.st_mtime_ns
        ) as stream:
            self.assertEqual(stream.read(), b'original-content')
        digest = sha256_verified_backup_source(
            self.file, self.metadata.st_size, self.metadata.st_mtime_ns)
        self.assertEqual(digest, hashlib.sha256(b'original-content').hexdigest())

    def test_rejects_replacement_between_stat_and_open_with_same_size_mtime(self):
        original = self.src / 'original-moved.bin'
        other = self.src / 'replacement.bin'
        other.write_bytes(b'INJECTED-CONTENT')
        self.assertEqual(other.stat().st_size, self.metadata.st_size)
        real_open = os.open
        swapped = [False]

        def swap_before_open(path, flags, *args, **kwargs):
            if Path(path) == self.file and not swapped[0]:
                swapped[0] = True
                self.file.rename(original)
                other.rename(self.file)
                os.utime(self.file, ns=(self.metadata.st_atime_ns,
                                        self.metadata.st_mtime_ns))
            return real_open(path, flags, *args, **kwargs)

        with patch.object(backup_source_guard.os, 'open', swap_before_open):
            with self.assertRaisesRegex(OSError, 'substituído'):
                with open_verified_backup_source(
                    self.file, self.metadata.st_size, self.metadata.st_mtime_ns
                ) as stream:
                    stream.read()
        self.assertTrue(swapped[0])
        self.assertEqual(original.read_bytes(), b'original-content')
        self.assertEqual(self.file.read_bytes(), b'INJECTED-CONTENT')

    def test_copy_rejects_source_replacement_at_open(self):
        plan = prepare_multi_source_preview([str(self.file)], [str(self.src)])
        moved = self.src / 'original-moved.bin'
        replacement = self.src / 'replacement.bin'
        replacement.write_bytes(b'INJECTED-CONTENT')
        real_open = os.open
        swapped = [False]

        def swap_before_open(path, flags, *args, **kwargs):
            if Path(path) == self.file and not swapped[0]:
                swapped[0] = True
                self.file.rename(moved)
                replacement.rename(self.file)
                os.utime(self.file, ns=(self.metadata.st_atime_ns,
                                        self.metadata.st_mtime_ns))
            return real_open(path, flags, *args, **kwargs)

        with (patch.object(backup_source_guard.os, 'open', swap_before_open),
              patch.object(backup_core, 'choose_strategy',
                           lambda a, b, inventory=None: choose_strategy(a, b, inventory={}))):
            folder, result = backup_core.copy_backup(
                plan, self.dst,
                test_space_probe=lambda p, d: (100 * 1024**3, 10 * 1024**3, True))
        self.assertTrue(swapped[0])
        self.assertEqual(result['status'], 'parcial_com_erros')
        self.assertFalse(result['files'])
        self.assertFalse(list(folder.rglob('*.partial-*')))
        self.assertEqual(moved.read_bytes(), b'original-content')

    def test_source_modified_after_plan_is_rejected(self):
        self.file.write_bytes(b'changed-content-long')
        with self.assertRaisesRegex(OSError, 'mudou'):
            with open_verified_backup_source(
                self.file, self.metadata.st_size, self.metadata.st_mtime_ns):
                self.fail('Altered source should never be read')


if __name__ == '__main__':
    unittest.main()
