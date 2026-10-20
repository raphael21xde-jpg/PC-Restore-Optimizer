"""Synthetic resume tests: interrupted multi-source copies must reverify data."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_core
from multi_source_plan import prepare_multi_source_preview
from selective_recovery import verify_complete_manifest
from transfer_engine import choose_strategy


class MultiSourceResumeTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix='pcro-resume-')
        self.addCleanup(t.cleanup)
        root = Path(t.name)
        self.src = root / 'source'
        self.dst = root / 'destination'
        self.src.mkdir()
        self.dst.mkdir()
        self.a = self.src / 'a.txt'
        self.b = self.src / 'b.txt'
        self.a.write_bytes(b'first synthetic source')
        self.b.write_bytes(b'second synthetic source')
        self.original_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (self.a, self.b)}
        self.plan = prepare_multi_source_preview(
            [str(self.a), str(self.b)], [str(self.src)])

    def copy(self, *, hook=None, resume=None):
        with patch.object(backup_core, 'choose_strategy',
                          lambda a, b, inventory=None: choose_strategy(a, b, inventory={})):
            return backup_core.copy_backup(
                self.plan, self.dst, resume_manifest=resume, test_fault_hook=hook,
                test_space_probe=lambda p, d: (100 * 1024**3, 10 * 1024**3, True))

    def interrupted(self):
        reads = [0]
        def hook(stage):
            if stage == 'backup_after_write':
                reads[0] += 1
                if reads[0] == 2:
                    raise OSError('synthetic device interruption')
        folder, report = self.copy(hook=hook)
        self.assertEqual(report['status'], 'parcial_com_erros')
        self.assertEqual(len(report['files']), 1)
        return folder

    def test_resume_reverifies_and_completes_two_files(self):
        folder = self.interrupted()
        resumed_folder, report = self.copy(resume=folder / 'manifest.json')
        self.assertEqual(folder, resumed_folder)
        self.assertEqual(report['status'], 'concluido')
        self.assertEqual(len(report['files']), 2)
        self.assertEqual(len({x['relative'] for x in report['files']}), 2)
        verified = verify_complete_manifest(folder / 'manifest.json')
        self.assertEqual(verified['files_verified'], 2)
        for p in (self.a, self.b):
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),
                             self.original_hashes[p.name])

    def test_corrupted_partial_copy_is_not_accepted_without_recopy(self):
        folder = self.interrupted()
        original_record = next(x for x in
                               __import__('json').loads((folder / 'manifest.json').read_text(
                                   encoding='utf-8'))['files'])
        backed = folder / original_record['relative']
        backed.write_bytes(b'X' * backed.stat().st_size)
        resumed_folder, report = self.copy(resume=folder / 'manifest.json')
        self.assertEqual(resumed_folder, folder)
        self.assertEqual(report['status'], 'concluido')
        self.assertEqual(verify_complete_manifest(folder / 'manifest.json')['files_verified'], 2)
        self.assertEqual(hashlib.sha256(backed.read_bytes()).hexdigest(),
                         original_record['sha256'])

    def test_completed_backup_cannot_be_resumed(self):
        folder, report = self.copy()
        self.assertEqual(report['status'], 'concluido')
        with self.assertRaisesRegex(ValueError, 'incompatível'):
            self.copy(resume=folder / 'manifest.json')


if __name__ == '__main__':
    unittest.main()
