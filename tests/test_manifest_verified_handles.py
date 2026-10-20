"""Manifest audit regressions: never trust a path-only hash after swaps.

All files are disposable fixtures created inside TemporaryDirectory.
No physical disks, formatting, or restoration to user locations.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import backup_source_guard
import selective_recovery
from multi_source_plan import prepare_multi_source_preview
from selective_recovery import run_selected_backup, verify_complete_manifest


class VerifiedManifestAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-manifest-handles-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = self.root / 'sources'
        self.backups = self.root / 'backups'
        self.sources.mkdir()
        self.backups.mkdir()
        self.data = b'original-backup-content'
        self.source = self.sources / 'payload.bin'
        self.source.write_bytes(self.data)
        self.plan = prepare_multi_source_preview(
            [str(self.source)], [str(self.sources)])

    def backup(self):
        result = run_selected_backup(
            self.plan, self.backups, test_root=str(self.root))
        manifest = Path(result['manifest'])
        destination = next(manifest.parent.rglob('payload.bin'))
        return manifest, destination

    def test_normal_handle_bound_manifest_audit_passes(self):
        manifest, destination = self.backup()
        report = verify_complete_manifest(manifest)
        self.assertTrue(report['backup_verified'])
        self.assertEqual(report['files_verified'], 1)
        self.assertEqual(destination.read_bytes(), self.data)

    def test_replacement_between_lstat_and_open_is_rejected(self):
        manifest, destination = self.backup()
        original_info = destination.stat()
        replacement = destination.with_name('replacement.bin')
        replacement.write_bytes(b'Z' * len(self.data))
        saved = destination.with_name('old-original.bin')
        original_open = os.open
        swapped = [False]

        def intercept_open(path, flags, *args, **kwargs):
            if Path(path) == destination and not swapped[0]:
                swapped[0] = True
                destination.rename(saved)
                replacement.rename(destination)
                os.utime(destination, ns=(
                    original_info.st_atime_ns, original_info.st_mtime_ns))
            return original_open(path, flags, *args, **kwargs)

        with patch.object(backup_source_guard.os, 'open', intercept_open):
            with self.assertRaises(OSError):
                verify_complete_manifest(manifest)
        self.assertTrue(swapped[0], 'Race injection did not execute')
        self.assertEqual(saved.read_bytes(), self.data)
        self.assertEqual(destination.read_bytes(), b'Z' * len(self.data))

    def test_replaced_parent_directory_is_rejected_even_with_same_bytes(self):
        manifest, destination = self.backup()
        original_parent = destination.parent
        saved_parent = original_parent.with_name(original_parent.name + '-saved')
        actual_verifier = selective_recovery.verify_committed_backup_file
        swapped = [False]

        def intercept_verify(folder, target, ancestry, size, sha, cancelled):
            if not swapped[0]:
                swapped[0] = True
                original_parent.rename(saved_parent)
                original_parent.mkdir()
                target.write_bytes(self.data)
            return actual_verifier(
                folder, target, ancestry, size, sha, cancelled)

        with patch.object(
            selective_recovery, 'verify_committed_backup_file', intercept_verify
        ):
            with self.assertRaises(OSError):
                verify_complete_manifest(manifest)
        self.assertTrue(swapped[0], 'Parent swap injection did not execute')
        self.assertEqual((saved_parent / destination.name).read_bytes(), self.data)
        self.assertEqual(destination.read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()
