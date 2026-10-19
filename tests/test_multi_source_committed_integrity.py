"""Verify final backup data before accepting a manifest entry.

All fault injection is confined to newly created temporary fixtures.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_core
from multi_source_plan import prepare_multi_source_preview
from selective_recovery import verify_complete_manifest
from transfer_engine import choose_strategy


class MultiSourceCommittedFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='pcro-committed-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = self.root / 'sources'
        self.backups = self.root / 'backups'
        self.sources.mkdir()
        self.backups.mkdir()
        self.source = self.sources / 'sample.dat'
        self.original = b'original fixture payload'
        self.source.write_bytes(self.original)
        self.plan = prepare_multi_source_preview(
            [str(self.source)], [str(self.sources)])

    def copy(self, after_commit=None):
        real_publish = backup_core.publish_copy
        activated = [False]

        def replace_with_fault(src, dst, previous=None):
            real_publish(src, dst, previous)
            if (after_commit is not None and not activated[0]
                    and '.partial-' in Path(src).name
                    and Path(dst).name == 'sample.dat'):
                activated[0] = True
                after_commit(Path(dst))

        with (patch.object(backup_core, 'publish_copy', replace_with_fault),
              patch.object(backup_core, 'choose_strategy',
                           lambda a, b, inventory=None: choose_strategy(a, b, inventory={}))):
            folder, result = backup_core.copy_backup(
                self.plan, self.backups,
                test_space_probe=lambda p, d: (100 * 1024**3, 10 * 1024**3, True))
        return folder, result, activated[0]

    def assert_rejected(self, folder, report):
        self.assertEqual(report['status'], 'parcial_com_erros')
        self.assertFalse(report['files'])
        self.assertTrue(report['errors'])
        with self.assertRaises((ValueError, OSError)):
            verify_complete_manifest(folder / 'manifest.json')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_normal_committed_file_is_verified(self):
        folder, result, activated = self.copy()
        self.assertFalse(activated)
        self.assertEqual(result['status'], 'concluido')
        self.assertEqual(len(result['files']), 1)
        self.assertTrue(verify_complete_manifest(folder / 'manifest.json')['backup_verified'])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_corruption_immediately_after_replace_is_not_verified(self):
        def corrupt(destination):
            destination.write_bytes(b'Z' * len(self.original))

        folder, result, activated = self.copy(corrupt)
        self.assertTrue(activated)
        self.assert_rejected(folder, result)

    def test_disappearing_committed_file_is_not_verified(self):
        def disconnect(destination):
            destination.unlink()

        folder, result, activated = self.copy(disconnect)
        self.assertTrue(activated)
        self.assert_rejected(folder, result)

    def test_replaced_parent_after_commit_is_not_verified(self):
        def swap_parent(destination):
            parent = destination.parent
            parent.rename(parent.with_name(parent.name + '-old'))
            parent.mkdir()
            destination.write_bytes(b'Z' * len(self.original))

        folder, result, activated = self.copy(swap_parent)
        self.assertTrue(activated)
        self.assert_rejected(folder, result)


if __name__ == '__main__':
    unittest.main()
