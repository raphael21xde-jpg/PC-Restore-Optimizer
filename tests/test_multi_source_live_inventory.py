"""Synthetic read-only tests for fresh disk inventory integration."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from multi_source_live_inventory import recheck_with_fresh_inventory


class FreshDiskInventoryTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix='pcro-fresh-disks-')
        self.addCleanup(t.cleanup)
        root = Path(t.name)
        self.a, self.b, self.c = [root / n for n in ('a', 'b', 'c')]
        for folder in (self.a, self.b, self.c):
            folder.mkdir()
        self.f1, self.f2 = self.a / 'a.txt', self.b / 'b.txt'
        self.f1.write_bytes(b'A')
        self.f2.write_bytes(b'B')
        self.plan = prepare_multi_source_preview(
            [str(self.f1), str(self.f2)], [str(self.a), str(self.b)])
        self.report = {
            'disks': [{'Number': n, 'BusType': 'SATA'} for n in (1, 2, 3)],
            'volumes': [{'DriveLetter': x, 'SizeRemaining': 100 * 1024**3}
                        for x in 'ABC'],
            'extent_mapping': {'volumes': [
                {'letters': [x], 'disk_numbers': [n],
                 'status': 'logical_disk_reported'}
                for x, n in [('A', 1), ('B', 2), ('C', 3)]]},
            'spaces_membership': {},
        }
        self.preview = preview_multi_source_targets(
            self.plan, [str(self.c)], volume_lookup=self.volume,
            usage=self.usage, disk_diagnostic=self.report)

    def volume(self, value):
        p = Path(value)
        for folder, drive in ((self.a, 'A:'), (self.b, 'B:'), (self.c, 'C:')):
            if p == folder or folder in p.parents:
                return drive
        return 'SEM UNIDADE'

    def usage(self, _):
        return SimpleNamespace(free=100 * 1024**3)

    def check(self, collector):
        return recheck_with_fresh_inventory(
            self.plan, self.preview, volume_lookup=self.volume,
            usage=self.usage, collector=collector)

    def test_fresh_matching_inventory_remains_unapproved(self):
        calls = []
        def collect():
            calls.append(True)
            return copy.deepcopy(self.report)
        result = self.check(collect)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result['fresh_inventory_rechecked'])
        self.assertFalse(result['backup_verified'])
        self.assertFalse(result['installation_authorized'])

    def test_changed_topology_requires_new_preview(self):
        def collect():
            report = copy.deepcopy(self.report)
            report['extent_mapping']['volumes'][-1]['disk_numbers'] = [2]
            return report
        with self.assertRaisesRegex(ValueError, 'Diagnóstico de discos alterado'):
            self.check(collect)

    def test_collector_failure_does_not_fall_back_to_cached_data(self):
        def collect():
            raise RuntimeError('PowerShell indisponível')
        with self.assertRaisesRegex(ValueError, 'Não foi possível atualizar'):
            self.check(collect)

    def test_incomplete_inventory_rejected(self):
        with self.assertRaisesRegex(ValueError, 'incompleto'):
            self.check(lambda: {'disks': []})

    def test_preview_without_diagnostic_rejected_without_collection(self):
        self.preview.pop('disk_diagnostic_sha256')
        calls = []
        with self.assertRaisesRegex(ValueError, 'Prévia sem diagnóstico'):
            self.check(lambda: calls.append(True))
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
