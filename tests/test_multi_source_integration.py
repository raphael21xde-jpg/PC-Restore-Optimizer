"""Integration rehearsal: multi-root planning -> preview -> verified copy/restore.

All I/O is contained in TemporaryDirectory. Production execution remains gated
by the existing C:-only flow until independent target validation is complete.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import backup_core
import backup_features
from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from selective_recovery import (run_selected_backup, run_isolated_restore_test,
                                verify_complete_manifest)
from transfer_engine import choose_strategy


def _fixture_strategy(source, target, inventory=None):
    return choose_strategy(source, target, inventory={})


class MultiSourceIntegratedRehearsalTests(unittest.TestCase):
    def setUp(self):
        sandbox = tempfile.TemporaryDirectory(prefix='PCRO-MULTI-E2E-')
        self.addCleanup(sandbox.cleanup)
        self.base = Path(sandbox.name)
        self.source_a = self.base / 'source_A'
        self.source_b = self.base / 'source_B'
        self.backups = self.base / 'backup_C'
        self.restores = self.base / 'restore_D'
        for folder in (self.source_a, self.source_b, self.backups, self.restores):
            folder.mkdir()
        self.a = self.source_a / 'documento.txt'
        self.b = self.source_b / 'save.dat'
        self.a.write_bytes(b'documento preservado')
        self.b.write_bytes(b'save preservado')
        self.expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (self.a, self.b)}

    def _volume(self, path):
        p = Path(path)
        for folder, letter in ((self.source_a, 'A:'), (self.source_b, 'B:'),
                               (self.backups, 'C:'), (self.restores, 'D:')):
            if p == folder or folder in p.parents:
                return letter
        return 'SEM UNIDADE'

    def test_copy_verify_and_isolated_restore_across_two_origins(self):
        plan = prepare_multi_source_preview(
            [str(self.a), str(self.b)], [str(self.source_a), str(self.source_b)])
        review = preview_multi_source_targets(
            plan, [str(self.backups)], volume_lookup=self._volume,
            usage=lambda _: SimpleNamespace(free=100 * 1024**3))
        self.assertEqual(review['source_volumes'], ['A:', 'B:'])
        self.assertFalse(review['backup_verified'])
        self.assertFalse(review['installation_authorized'])
        # Portable sandbox ONLY: the old executor is not exposed to the real UI.
        with (patch.object(backup_core, 'choose_strategy', _fixture_strategy),
              patch.object(backup_features, 'choose_strategy', _fixture_strategy)):
            backup = run_selected_backup(plan, self.backups, test_root=str(self.base))
            verified = verify_complete_manifest(backup['manifest'])
            restored = run_isolated_restore_test(
                backup['manifest'], self.restores, test_root=str(self.base))
        self.assertTrue(verified['backup_verified'])
        self.assertEqual(verified['files_verified'], 2)
        self.assertTrue(restored['restore_verified'])
        self.assertFalse(restored['ready_for_format'])
        recovered = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in Path(restored['restored_folder']).rglob('*')
                     if p.is_file() and p.name in self.expected}
        self.assertEqual(recovered, self.expected)
        for source in (self.a, self.b):
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                             self.expected[source.name])

    def test_target_on_source_volume_blocks_before_copy(self):
        plan = prepare_multi_source_preview(
            [str(self.a), str(self.b)], [str(self.source_a), str(self.source_b)])
        with self.assertRaisesRegex(ValueError, 'mesma unidade'):
            preview_multi_source_targets(
                plan, [str(self.source_b)], volume_lookup=self._volume,
                usage=lambda _: SimpleNamespace(free=100 * 1024**3))
        self.assertFalse(list(self.backups.iterdir()))
        self.assertFalse(list(self.restores.iterdir()))


if __name__ == '__main__':
    unittest.main()
