"""Synthetic physical/logical disk preflight for multi-source destination preview.

Disk numbers are NOT proof of physical independence. No real disk I/O.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from multi_source_recheck import recheck_multi_source_preview


class MultiSourceDiskMappingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-disk-map-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.dirs = {letter: root / letter for letter in 'ABCD'}
        for folder in self.dirs.values():
            folder.mkdir()
        files = []
        for letter in 'AB':
            filename = self.dirs[letter] / (letter + '.txt')
            filename.write_bytes(letter.encode())
            files.append(str(filename))
        self.plan = prepare_multi_source_preview(
            files, [str(self.dirs['A']), str(self.dirs['B'])])

    def volume(self, path):
        path = Path(path)
        for letter, folder in self.dirs.items():
            if path == folder or folder in path.parents:
                return letter + ':'
        return 'SEM UNIDADE'

    def diagnostic(self, *, target_disks=(3,), source_b_disks=(2,),
                   remove_target=False):
        mapping = [('A', [1]), ('B', list(source_b_disks))]
        if not remove_target:
            mapping.append(('C', list(target_disks)))
        return {
            'disks': [{'Number': n, 'BusType': 'SATA'} for n in (1, 2, 3)],
            'volumes': [{'DriveLetter': x, 'SizeRemaining': 100 * 1024**3}
                        for x in 'ABC'],
            'extent_mapping': {'volumes': [
                {'letters': [letter], 'disk_numbers': disks,
                 'status': 'logical_disk_reported' if len(disks) == 1 else 'multi_disk'}
                for letter, disks in mapping]},
            'spaces_membership': {},
        }

    def preview(self, diagnostic):
        return preview_multi_source_targets(
            self.plan, [str(self.dirs['C'])],
            volume_lookup=self.volume,
            usage=lambda _: SimpleNamespace(free=100 * 1024**3),
            disk_diagnostic=diagnostic)

    def test_overlap_with_first_source_disk_blocked(self):
        with self.assertRaisesRegex(ValueError, 'Conflito entre discos'):
            self.preview(self.diagnostic(target_disks=(1,)))

    def test_overlap_with_second_source_disk_blocked(self):
        with self.assertRaisesRegex(ValueError, 'Conflito entre discos'):
            self.preview(self.diagnostic(target_disks=(2,)))

    def test_multi_disk_target_with_one_shared_extent_blocked(self):
        with self.assertRaisesRegex(ValueError, 'Conflito entre discos'):
            self.preview(self.diagnostic(target_disks=(2, 3)))

    def test_disjoint_logical_disks_remain_review_only(self):
        result = self.preview(self.diagnostic())
        self.assertFalse(result['physical_independence_verified'])
        self.assertFalse(result['installation_authorized'])
        target = result['destinations'][0]
        self.assertEqual(target['logical_disk_numbers'], [3])
        self.assertEqual(target['preflight_status'], 'requires_review')

    def test_missing_mapping_never_claims_independence(self):
        result = self.preview(self.diagnostic(remove_target=True))
        target = result['destinations'][0]
        self.assertEqual(target['logical_disk_numbers'], [])
        self.assertEqual(target['preflight_status'], 'requires_review')
        self.assertFalse(result['physical_independence_verified'])

    def _recheck(self, saved, current):
        return recheck_multi_source_preview(
            self.plan, saved, volume_lookup=self.volume,
            usage=lambda _: SimpleNamespace(free=100 * 1024**3),
            disk_diagnostic=current)

    def test_same_diagnostic_recheck_remains_review_only(self):
        snapshot = self.diagnostic()
        saved = self.preview(snapshot)
        checked = self._recheck(saved, snapshot)
        self.assertEqual(checked['disk_diagnostic_sha256'],
                         saved['disk_diagnostic_sha256'])
        self.assertFalse(checked['backup_verified'])
        self.assertFalse(checked['installation_authorized'])

    def test_changed_extent_mapping_rejected_before_copy(self):
        saved = self.preview(self.diagnostic())
        changed = self.diagnostic(target_disks=(2,))
        with self.assertRaisesRegex(ValueError, 'Diagnóstico de discos alterado'):
            self._recheck(saved, changed)

    def test_missing_fresh_diagnostic_rejected(self):
        saved = self.preview(self.diagnostic())
        with self.assertRaisesRegex(ValueError, 'Diagnóstico atualizado obrigatório'):
            self._recheck(saved, None)

    def test_new_diagnostic_rejected_for_old_preview(self):
        saved = self.preview(self.diagnostic())
        saved.pop('disk_diagnostic_sha256')
        with self.assertRaisesRegex(ValueError, 'Prévia antiga sem diagnóstico'):
            self._recheck(saved, self.diagnostic())

    def test_reject_malformed_diagnostic(self):
        with self.assertRaisesRegex(ValueError, 'Diagnóstico de discos inválido'):
            self.preview([])


if __name__ == '__main__':
    unittest.main()
