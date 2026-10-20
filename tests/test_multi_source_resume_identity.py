"""Safety regressions for reused data during an interrupted fixture backup."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_core
import backup_source_guard
from multi_source_plan import prepare_multi_source_preview
from selective_recovery import verify_complete_manifest
from transfer_engine import choose_strategy


class MultiSourceResumeIdentityTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix='pcro-resume-identity-')
        self.addCleanup(t.cleanup)
        root = Path(t.name)
        self.src = root / 'sources'
        self.dst = root / 'backups'
        self.src.mkdir()
        self.dst.mkdir()
        self.a = self.src / 'a.dat'
        self.b = self.src / 'b.dat'
        self.a.write_bytes(b'original-A-contents')
        self.b.write_bytes(b'original-B-contents')
        self.plan = prepare_multi_source_preview(
            [str(self.a), str(self.b)], [str(self.src)])

    def copy(self, resume=None, fault=None):
        with patch.object(backup_core, 'choose_strategy',
                          lambda a, b, inventory=None: choose_strategy(a, b, inventory={})):
            return backup_core.copy_backup(
                self.plan, self.dst, resume_manifest=resume, test_fault_hook=fault,
                test_space_probe=lambda p, d: (100 * 1024**3, 10 * 1024**3, True))

    def partial(self):
        writes = [0]
        def fail_second(stage):
            if stage == 'backup_after_write':
                writes[0] += 1
                if writes[0] == 2:
                    raise OSError('interrupção sintética do destino')
        folder, result = self.copy(fault=fail_second)
        self.assertEqual(result['status'], 'parcial_com_erros')
        self.assertEqual(len(result['files']), 1)
        return folder

    def test_source_changed_with_same_size_and_timestamp_is_not_skipped(self):
        folder = self.partial()
        original = self.a.stat()
        changed = b'CHANGED!-A-contents'
        self.assertEqual(len(changed), len(self.a.read_bytes()))
        self.a.write_bytes(changed)
        os.utime(self.a, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(self.a.stat().st_mtime_ns, original.st_mtime_ns)

        _, result = self.copy(resume=folder / 'manifest.json')
        self.assertEqual(result['status'], 'parcial_com_erros')
        self.assertTrue(any('Fonte diverge' in x.get('error', '')
                            for x in result['errors']))
        with self.assertRaises((ValueError, OSError)):
            verify_complete_manifest(folder / 'manifest.json')

    def test_replaced_destination_between_stat_and_open_is_rejected(self):
        folder = self.partial()
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        backed = folder / manifest['files'][0]['relative']
        original = backed.read_bytes()
        candidate = backed.with_name(backed.name + '-candidate')
        moved = backed.with_name(backed.name + '-old')
        candidate.write_bytes(original)
        st = backed.stat()
        os.utime(candidate, ns=(st.st_atime_ns, st.st_mtime_ns))
        real_open = os.open
        swapped = [False]

        def swap_before_open(path, flags, *args, **kwargs):
            if Path(path) == backed and not swapped[0]:
                swapped[0] = True
                backed.rename(moved)
                candidate.rename(backed)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(backup_source_guard.os, 'open', swap_before_open):
            _, result = self.copy(resume=folder / 'manifest.json')
        self.assertTrue(swapped[0])
        self.assertEqual(result['status'], 'parcial_com_erros')
        self.assertTrue(any('substituído' in x.get('error', '')
                            for x in result['errors']))
        self.assertEqual(moved.read_bytes(), original)
        self.assertEqual(self.a.read_bytes(), b'original-A-contents')


if __name__ == '__main__':
    unittest.main()
