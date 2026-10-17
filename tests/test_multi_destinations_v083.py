"""Multi-destination checks with temporary files only; no real disks."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from backup_core import FileTask, Plan
import multi_backup_destinations as multi
from selective_recovery import run_selected_backup, verify_complete_manifest


class MultiDestinationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'source'
        self.src.mkdir()
        self.original = self.src / 'sample.txt'
        self.original.write_text('arquivo de origem intacto', encoding='utf-8')
        self.target1 = self.root / 'target_external'
        self.target2 = self.root / 'target_sync'
        self.target1.mkdir()
        self.target2.mkdir()
        st = self.original.stat()
        self.plan = Plan(
            files=[FileTask(str(self.original), st.st_size, st.st_mtime_ns,
                            'TEST/sample.txt')],
            selected=[str(self.original)], total=st.st_size)
        self.destinations = [
            {'path': str(self.target1), 'kind': 'external'},
            {'path': str(self.target2), 'kind': 'synced_folder'}]

    def prepare(self, destinations=None, **kwargs):
        # No actual Windows disk needs to exist for this unit test.
        def fake_volume(path):
            val = str(path)
            if 'target_external' in val:
                return 'E:'
            if 'target_sync' in val:
                return 'G:'
            return 'C:'
        with patch.object(multi, 'volume_of', side_effect=fake_volume):
            return multi.make_multi_backup_plan(
                self.plan, destinations if destinations is not None else self.destinations,
                usage=lambda p: SimpleNamespace(free=100 * 1024**3), **kwargs)

    def test_multiple_destinations_planned_without_claiming_cloud_or_physical_safety(self):
        result = self.prepare()
        self.assertEqual(result['copies_requested'], 2)
        self.assertEqual(result['estimated_total_copy_bytes'], self.plan.total * 2)
        self.assertFalse(result['cloud_upload_verified'])
        self.assertFalse(result['physical_independence_verified'])
        self.assertFalse(result['approved_for_format'])
        self.assertTrue(all(row['preflight_status'] == 'requires_review'
                            for row in result['destinations']))

    def test_real_copies_to_two_temporary_directories_and_verify_sha256(self):
        plan = self.prepare()
        def temp_runner(plan, folder, **kwargs):
            return run_selected_backup(plan, folder, test_root=str(self.root), **kwargs)
        result = multi.run_multiple_backups(self.plan, plan, backup_runner=temp_runner)
        self.assertEqual(result['status'], 'all_local_copies_verified')
        self.assertEqual(result['copies_verified_locally'], 2)
        self.assertEqual(result['copies_requested'], 2)
        for item in result['destinations']:
            verified = verify_complete_manifest(item['manifest'])
            self.assertTrue(verified['backup_verified'])
            self.assertEqual(verified['bytes_verified'], self.plan.total)
            self.assertFalse(item['cloud_upload_verified'])
        self.assertEqual(self.original.read_text(encoding='utf-8'),
                         'arquivo de origem intacto')
        self.assertFalse(result['cloud_upload_verified'])
        self.assertFalse(result['ready_for_format'])
        self.assertFalse(result['installation_authorized'])

    def test_fail_first_destination_stops_all_later_copies(self):
        plan = self.prepare()
        calls = []
        def runner(plan, folder, **kwargs):
            calls.append(folder)
            raise OSError('unidade retirada')
        result = multi.run_multiple_backups(self.plan, plan, backup_runner=runner)
        self.assertEqual(result['status'], 'not_verified')
        self.assertEqual(result['copies_verified_locally'], 0)
        self.assertEqual(len(calls), 1)

    def test_cancel_between_destinations_is_not_complete(self):
        plan = self.prepare()
        stop = threading.Event()
        def runner(plan, folder, **kwargs):
            stop.set()
            return {'backup_verified': True, 'manifest': 'manifest.json',
                    'backup_folder': folder, 'files_verified': 1,
                    'bytes_verified': self.plan.total}
        result = multi.run_multiple_backups(self.plan, plan, backup_runner=runner,
                                            cancelled=stop)
        self.assertEqual(result['status'], 'partially_verified')
        self.assertEqual(result['copies_verified_locally'], 1)
        self.assertEqual(result['destinations'][-1]['status'], 'cancelled_before_copy')

    def test_synced_folder_does_not_mean_cloud_verified(self):
        plan = self.prepare()
        results = []
        def runner(plan, folder, **kwargs):
            results.append(folder)
            return {'backup_verified': True, 'manifest': 'manifest.json',
                    'backup_folder': folder, 'files_verified': 1,
                    'bytes_verified': self.plan.total}
        report = multi.run_multiple_backups(self.plan, plan, backup_runner=runner)
        self.assertFalse(report['cloud_upload_verified'])
        self.assertEqual(len(results), 2)

    def test_rejects_source_inside_destination_and_vice_versa(self):
        for folder in (self.src, self.original.parent):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                self.prepare([{'path': str(folder), 'kind': 'local'}])

    def test_rejects_duplicate_and_nested_destinations(self):
        nested = self.target1 / 'nested'
        nested.mkdir()
        for collection in (
            [self.destinations[0], self.destinations[0]],
            [self.destinations[0], {'path': str(nested), 'kind': 'local'}],
        ):
            with self.subTest(collection=collection), self.assertRaises(ValueError):
                self.prepare(collection)

    def test_direct_cloud_api_cannot_be_used_without_implementation(self):
        with self.assertRaisesRegex(ValueError, 'Nuvem direta'):
            self.prepare([{'path': str(self.target2), 'kind': 'cloud_direct'}])

    def test_invalid_or_over_limit_selected_destinations_rejected(self):
        for selections in ([], self.destinations * 5):
            with self.subTest(count=len(selections)), self.assertRaises(ValueError):
                self.prepare(selections)

    def test_space_reserve_prevents_risky_copy(self):
        with patch.object(multi, 'volume_of',
                          side_effect=lambda p: 'E:' if 'target_external' in str(p) else 'C:'):
            with self.assertRaisesRegex(ValueError, 'Sem espaço suficiente'):
                multi.make_multi_backup_plan(
                    self.plan, self.destinations[:1],
                    usage=lambda p: SimpleNamespace(free=1024))

    def test_symlink_destination_rejected(self):
        link = self.root / 'alias'
        try:
            link.symlink_to(self.target1, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Sem permissão para criar link no sistema de testes.')
        with self.assertRaisesRegex(ValueError, 'link ou junção'):
            self.prepare([{'path': str(link), 'kind': 'external'}])

    def test_preflight_existing_extent_collision_blocks_before_writes(self):
        diag = {
            'disks': [{'Number': 2, 'BusType': 'NVMe'}],
            'volumes': [
                {'DriveLetter': 'C', 'SizeRemaining': 80 * 1024**3},
                {'DriveLetter': 'E', 'SizeRemaining': 80 * 1024**3}],
            'extent_mapping': {'volumes': [
                {'letters': ['C'], 'disk_numbers': [2], 'status': 'reported'},
                {'letters': ['E'], 'disk_numbers': [2], 'status': 'reported'},
            ]},
            'spaces_membership': {},
        }
        with self.assertRaisesRegex(ValueError, 'Conflito'):
            self.prepare(self.destinations[:1], disk_diagnostic=diag)

    def test_tampered_plan_rejected(self):
        with self.assertRaises(ValueError):
            multi.run_multiple_backups(self.plan, {})
        self.plan.warnings.append('erro de varredura')
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
