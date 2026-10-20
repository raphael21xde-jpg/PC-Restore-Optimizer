"""Synthetic-only tests for the fresh, read-only disk mapping report."""
import copy
import json
import unittest

from drive_safety_report import inspect_fresh_drive_safety


class FreshDriveSafetyReportTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            'disks': [
                {'Number': 0, 'BusType': 'NVMe', 'IsBoot': True,
                 'IsSystem': True, 'SerialNumber': 'private-disk-serial'},
                {'Number': 1, 'BusType': 'SATA'},
                {'Number': 2, 'BusType': 'USB'},
            ],
            'volumes': [
                {'DriveLetter': x, 'SizeRemaining': 100 * 1024**3,
                 'Path': r'\\?\Volume{private-guid}'}
                for x in ('C', 'D', 'E')
            ],
            'partitions': [
                {'DiskNumber': 0, 'IsSystem': True, 'Type': 'System'}
            ],
            'extent_mapping': {
                'volumes': [
                    {'letters': ['C'], 'disk_numbers': [0],
                     'status': 'logical_disk_reported'},
                    {'letters': ['D'], 'disk_numbers': [1],
                     'status': 'logical_disk_reported'},
                    {'letters': ['E'], 'disk_numbers': [2],
                     'status': 'logical_disk_reported'},
                ],
            },
            'spaces_membership': {},
            'alerts': ['Very sensitive information: private-serial'],
        }

    def run_review(self, *, sources=('C:',), targets=('D:',),
                   snapshot=None, estimated=100):
        calls = []
        def collector():
            calls.append(1)
            return copy.deepcopy(self.report if snapshot is None else snapshot)
        result = inspect_fresh_drive_safety(
            sources, targets, collector=collector,
            expected_backup_bytes=estimated)
        self.assertEqual(calls, [1])
        return result

    def assert_unapproved(self, review):
        self.assertFalse(review['copy_authorized'])
        self.assertFalse(review['backup_verified'])
        self.assertFalse(review['physical_independence_verified'])
        self.assertFalse(review['ready_for_format'])
        self.assertFalse(review['installation_authorized'])

    def test_distinct_logical_disks_are_review_only(self):
        result = self.run_review()
        self.assertEqual(result['status'], 'requires_review')
        self.assertEqual(result['inventory_status'], 'fresh_collected')
        self.assertEqual(result['destinations'][0]['extent_status'],
                         'observed_logical_only')
        self.assertEqual(result['destinations'][0]['logical_disk_numbers'], [1])
        self.assert_unapproved(result)

    def test_same_logical_disk_is_explicitly_blocked(self):
        doc = copy.deepcopy(self.report)
        doc['extent_mapping']['volumes'][1]['disk_numbers'] = [0]
        result = self.run_review(snapshot=doc)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any('compartilham' in x
                            for x in result['destinations'][0]['blockers']))
        self.assert_unapproved(result)

    def test_boot_disk_vetoes_even_with_distinct_source(self):
        result = self.run_review(sources=('D:',), targets=('C:',))
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any('EFI' in x
                            for x in result['destinations'][0]['blockers']))
        self.assert_unapproved(result)

    def test_missing_extent_mapping_blocks_instead_of_guessing(self):
        doc = copy.deepcopy(self.report)
        doc['extent_mapping']['volumes'] = [
            row for row in doc['extent_mapping']['volumes']
            if 'D' not in row['letters']]
        result = self.run_review(snapshot=doc)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['destinations'][0]['extent_status'], 'incomplete')
        self.assertEqual(result['destinations'][0]['logical_disk_numbers'], [])
        self.assert_unapproved(result)

    def test_duplicate_mapping_for_one_letter_is_ambiguous(self):
        doc = copy.deepcopy(self.report)
        doc['extent_mapping']['volumes'].append(
            {'letters': ['D'], 'disk_numbers': [2],
             'status': 'logical_disk_reported'})
        result = self.run_review(snapshot=doc)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['destinations'][0]['extent_status'], 'incomplete')

    def test_failed_collector_raises_without_fallback(self):
        def fail():
            raise RuntimeError('PowerShell disconnected')
        with self.assertRaisesRegex(ValueError, 'Não foi possível coletar'):
            inspect_fresh_drive_safety(['C'], ['D'], collector=fail)

    def test_incomplete_inventory_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'incompleto'):
            inspect_fresh_drive_safety(
                ['C'], ['D'], collector=lambda: {'disks': []})

    def test_invalid_drive_letters_rejected_before_collecting(self):
        calls = []
        def collect():
            calls.append(True)
            return self.report
        for sources, targets in (
            (['C', 'C:'], ['D']),
            (['C:\\Windows'], ['D']),
            (['C'], ['D', 'D:']),
            ([], ['D']),
        ):
            with self.subTest(sources=sources, targets=targets):
                with self.assertRaises(ValueError):
                    inspect_fresh_drive_safety(
                        sources, targets, collector=collect)
        self.assertEqual(calls, [])

    def test_no_serials_guids_or_other_sensitive_raw_data_returned(self):
        result = self.run_review(targets=('D:', 'E:'))
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn('private-disk-serial', encoded)
        self.assertNotIn('private-guid', encoded)
        self.assertNotIn('private-serial', encoded)
        self.assertNotIn('SerialNumber', encoded)
        self.assertFalse(result['raw_identifiers_included'])
        self.assertEqual(len(result['destinations']), 2)
        self.assert_unapproved(result)

    def test_insufficient_space_remains_blocked(self):
        doc = copy.deepcopy(self.report)
        doc['volumes'][1]['SizeRemaining'] = 9
        result = self.run_review(snapshot=doc, estimated=10)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['destinations'][0]['capacity_status'],
                         'insufficient')
        self.assert_unapproved(result)

    def test_missing_source_map_stays_blocked(self):
        doc = copy.deepcopy(self.report)
        doc['extent_mapping']['volumes'] = [
            row for row in doc['extent_mapping']['volumes']
            if 'C' not in row['letters']]
        result = self.run_review(snapshot=doc)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any('origens não confirmado' in x for x in
                            result['destinations'][0]['blockers']))
        self.assert_unapproved(result)

    def test_multiple_sources_and_targets_not_assumed_physical(self):
        result = self.run_review(
            sources=('C:', 'D:'), targets=('E:',))
        self.assertEqual(result['status'], 'requires_review')
        self.assertEqual(len(result['source_volumes']), 2)
        self.assertEqual(result['destinations'][0]['logical_disk_numbers'], [2])
        self.assert_unapproved(result)


if __name__ == '__main__':
    unittest.main()
