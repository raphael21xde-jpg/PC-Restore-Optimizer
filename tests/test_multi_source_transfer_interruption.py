"""Fault injection for long-running fixture backups; no real disks touched."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_core
from selective_recovery import verify_complete_manifest
from multi_source_plan import prepare_multi_source_preview
from transfer_engine import choose_strategy


class MultiSourceTransferInterruptionTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix='pcro-transfer-interruption-')
        self.addCleanup(t.cleanup)
        self.base = Path(t.name)
        self.src = self.base / 'source'
        self.dst = self.base / 'destination'
        self.src.mkdir()
        self.dst.mkdir()
        self.original = self.src / 'large-fixture.bin'
        self.original.write_bytes(b'x' * (3 * 1024 * 1024))
        self.source_hash = hashlib.sha256(self.original.read_bytes()).hexdigest()
        self.plan = prepare_multi_source_preview([str(self.original)], [str(self.src)])

    def copy(self, *, hook=None, resume_manifest=None):
        with patch.object(backup_core, 'choose_strategy',
                          lambda a, b, inventory=None: choose_strategy(a, b, inventory={})):
            return backup_core.copy_backup(
                self.plan, self.dst, test_fault_hook=hook,
                resume_manifest=resume_manifest,
                test_space_probe=lambda p, d: (100 * 1024**3, 10 * 1024**3, True))

    def test_interrupted_destination_write_not_verified_or_restorable(self):
        triggered = [False]
        def fault(stage):
            if stage == 'backup_after_write' and not triggered[0]:
                triggered[0] = True
                raise OSError('destino removido durante transferência (simulação)')
        folder, report = self.copy(hook=fault)
        self.assertTrue(triggered[0])
        self.assertEqual(report['status'], 'parcial_com_erros')
        self.assertFalse(report['files'])
        self.assertFalse(list(folder.rglob('*.partial-*')))
        with self.assertRaises((ValueError, OSError)):
            verify_complete_manifest(folder / 'manifest.json')
        self.assertEqual(hashlib.sha256(self.original.read_bytes()).hexdigest(),
                         self.source_hash)

    def test_resume_after_failed_write_requires_matching_source_plan(self):
        def fault(stage):
            if stage == 'backup_after_write':
                raise OSError('destino indisponível (simulação)')
        folder, report = self.copy(hook=fault)
        self.assertEqual(report['status'], 'parcial_com_erros')
        # Even with a valid interrupted manifest, source identity must match.
        self.original.write_bytes(b'changed source')
        changed = prepare_multi_source_preview([str(self.original)], [str(self.src)])
        with patch.object(self, 'plan', changed):
            with self.assertRaisesRegex(ValueError, 'plano de origem modificado'):
                self.copy(resume_manifest=folder / 'manifest.json')
        with self.assertRaises((ValueError, OSError)):
            verify_complete_manifest(folder / 'manifest.json')


if __name__ == '__main__':
    unittest.main()
