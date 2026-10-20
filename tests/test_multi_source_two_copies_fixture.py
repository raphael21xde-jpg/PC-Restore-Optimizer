"""Two-source, two-destination backup and restore rehearsals in a private sandbox.

These tests use only TemporaryDirectory fixtures and do not authorize real
multi-disk copying, cleanup, formatting, or Windows installation.
"""
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import backup_core
import multi_source_fixture_runner as fixture
from backup_features import restore_selected, verified_entries
from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from transfer_engine import choose_strategy


class MultiSourceTwoCopiesFixtureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-two-copies-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source_a = self.root / 'source_A'
        self.source_b = self.root / 'source_B'
        self.target_a = self.root / 'target_T'
        self.target_b = self.root / 'target_U'
        self.restore_parent = self.root / 'restores'
        for folder in (self.source_a, self.source_b, self.target_a,
                       self.target_b, self.restore_parent):
            folder.mkdir()
        self.first = self.source_a / 'a.txt'
        self.second = self.source_b / 'b.sav'
        self.first.write_bytes(b'important-document')
        self.second.write_bytes(b'important-game-save')
        self.expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (self.first, self.second)}
        self.plan = prepare_multi_source_preview(
            [str(self.first), str(self.second)],
            [str(self.source_a), str(self.source_b)])
        self.preview = self.make_preview()

    def volume(self, raw):
        path = Path(raw)
        for folder, drive in (
                (self.source_a, 'A:'), (self.source_b, 'B:'),
                (self.target_a, 'T:'), (self.target_b, 'U:')):
            if path == folder or folder in path.parents:
                return drive
        return 'SEM UNIDADE'

    @staticmethod
    def usage(_):
        return SimpleNamespace(free=100 * 1024 ** 3)

    def make_preview(self, paths=None, volume=None):
        return preview_multi_source_targets(
            self.plan,
            paths or [str(self.target_a), str(self.target_b)],
            usage=self.usage, volume_lookup=volume or self.volume)

    def run_copies(self, preview=None, cancelled=None):
        # Keep hardware probes out of isolated fixture runs.
        with patch.object(
            backup_core, 'choose_strategy',
            lambda src, dst, inventory=None:
                choose_strategy(src, dst, inventory={})):
            return fixture.run_multi_source_fixture_backups(
                self.plan, self.preview if preview is None else preview,
                test_root=str(self.root), volume_lookup=self.volume,
                usage=self.usage, cancelled=cancelled)

    def assert_sources_unchanged(self):
        self.assertEqual(
            self.expected,
            {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (self.first, self.second)})

    def test_two_verified_copies_both_restore_into_new_folders(self):
        result = self.run_copies()
        self.assertEqual(result['status'], 'all_local_copies_verified')
        self.assertEqual(result['copies_verified_locally'], 2)
        self.assertEqual(result['copies_requested'], 2)
        self.assertTrue(result['backup_verified'])
        self.assertFalse(result['physical_independence_verified'])
        self.assertFalse(result['installation_authorized'])
        self.assertFalse(result['ready_for_format'])
        for row in result['destinations']:
            self.assertEqual(row['status'], 'local_copy_verified')
            manifest = Path(row['manifest'])
            self.assertTrue(manifest.is_file())
            keys = list(verified_entries(manifest))
            self.assertEqual(len(keys), 2)
            restored, count = restore_selected(
                manifest, keys, self.restore_parent, strategy_inventory={})
            self.assertEqual(count, 2)
            recovered = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in restored.rglob('*')
                         if p.is_file() and p.name in self.expected}
            self.assertEqual(recovered, self.expected)
        self.assert_sources_unchanged()

    def test_bad_second_destination_blocks_before_first_copy(self):
        outside = tempfile.TemporaryDirectory(prefix='pcro-outside-')
        self.addCleanup(outside.cleanup)
        external = Path(outside.name).resolve()
        def fake_volume(raw):
            path = Path(raw)
            if path == external or external in path.parents:
                return 'V:'
            return self.volume(raw)
        preview = self.make_preview(
            [str(self.target_a), str(external)], volume=fake_volume)
        with self.assertRaisesRegex(ValueError, 'fora da raiz isolada'):
            fixture.run_multi_source_fixture_backups(
                self.plan, preview, test_root=str(self.root),
                volume_lookup=fake_volume, usage=self.usage)
        self.assertEqual(list(self.target_a.iterdir()), [])
        self.assertEqual(list(self.target_b.iterdir()), [])
        self.assert_sources_unchanged()

    def test_modified_source_blocks_all_destinations_before_copy(self):
        self.second.write_bytes(b'changed-after-preview')
        with self.assertRaisesRegex(ValueError, 'modificada'):
            self.run_copies()
        self.assertEqual(list(self.target_a.iterdir()), [])
        self.assertEqual(list(self.target_b.iterdir()), [])

    def test_second_copy_failure_cannot_claim_all_copies_verified(self):
        actual = fixture.run_multi_source_fixture_backup
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise OSError('second destination unavailable')
            return actual(*args, **kwargs)

        with patch.object(fixture, 'run_multi_source_fixture_backup',
                          side_effect=fail_second):
            result = self.run_copies()
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['status'], 'partially_verified')
        self.assertEqual(result['copies_verified_locally'], 1)
        self.assertFalse(result['backup_verified'])
        self.assertFalse(result['installation_authorized'])
        self.assertEqual(
            [row['status'] for row in result['destinations']],
            ['local_copy_verified', 'failed_or_interrupted'])
        self.assertTrue(list(self.target_a.rglob('manifest.json')))
        self.assertEqual(list(self.target_b.iterdir()), [])
        self.assert_sources_unchanged()

    def test_cancel_between_destinations_reports_partial(self):
        cancelled = threading.Event()
        actual = fixture.run_multi_source_fixture_backup

        def stop_after_first(*args, **kwargs):
            result = actual(*args, **kwargs)
            cancelled.set()
            return result

        with patch.object(fixture, 'run_multi_source_fixture_backup',
                          side_effect=stop_after_first):
            result = self.run_copies(cancelled=cancelled)
        self.assertEqual(result['status'], 'partially_verified')
        self.assertEqual(result['copies_verified_locally'], 1)
        self.assertFalse(result['backup_verified'])
        self.assertFalse(result['ready_for_format'])
        self.assertEqual(
            [row['status'] for row in result['destinations']],
            ['local_copy_verified', 'cancelled_before_copy'])
        self.assertEqual(list(self.target_b.iterdir()), [])
        self.assert_sources_unchanged()


if __name__ == '__main__':
    unittest.main()
