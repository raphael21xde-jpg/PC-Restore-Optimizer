"""Tests use simulated reports; no real disk operations."""
import unittest

from storage_consistency import assess_storage_mapping


class StorageConsistencyTests(unittest.TestCase):
    def sample(self, *, partitions=None, disks=None, volumes=None, partition_error=None):
        if disks is None:
            disks = [{'Number': 2, 'BusType': 'NVMe'},
                     {'Number': 3, 'BusType': 'NVMe'},
                     {'Number': 4, 'BusType': 'Spaces'}]
        if partitions is None:
            partitions = [{'DiskNumber': 2, 'DriveLetter': 'C'},
                          {'DiskNumber': 3, 'DriveLetter': 'D'},
                          {'DiskNumber': 4, 'DriveLetter': 'G'}]
        if volumes is None:
            volumes = [{'DriveLetter': 'C'}, {'DriveLetter': 'D'},
                       {'DriveLetter': 'F'}, {'DriveLetter': 'G'}]
        return assess_storage_mapping(disks, partitions, volumes,
                                      partition_error=partition_error)

    def test_f_missing_mapping_in_realistic_report(self):
        result = self.sample()
        by_letter = {m['letter']: m for m in result['letter_mapping']}
        self.assertEqual(result['status'], 'requires_review')
        self.assertEqual(by_letter['F']['status'], 'unverified')
        self.assertEqual(by_letter['C']['disk_numbers'], [2])
        self.assertIn('Espaços de Armazenamento', ' '.join(result['issues']))
        self.assertFalse(result['approved_for_format'])
        self.assertFalse(result['backup_destination_verified'])

    def test_partition_refers_to_disk_absent_from_get_disk(self):
        result = self.sample(partitions=[
            {'DiskNumber': 1, 'DriveLetter': 'F'},
            {'DiskNumber': 2, 'DriveLetter': 'C'},
        ])
        by_letter = {m['letter']: m for m in result['letter_mapping']}
        self.assertEqual(by_letter['F']['status'], 'disk_not_listed')
        self.assertEqual(result['partition_disks_not_listed'], [1])

    def test_multiple_disk_numbers_is_ambiguous(self):
        r = assess_storage_mapping([{'Number': 1}, {'Number': 2}],
                                   [{'DiskNumber': 1, 'DriveLetter': 'P'},
                                    {'DiskNumber': 2, 'DriveLetter': 'P'}],
                                   [{'DriveLetter': 'P'}])
        self.assertEqual(r['letter_mapping'][0]['status'], 'ambiguous')

    def test_even_consistent_metadata_does_not_approve_anything(self):
        r = assess_storage_mapping([{'Number': 2, 'BusType': 'NVMe'}],
                                   [{'DiskNumber': 2, 'DriveLetter': 'C'}],
                                   [{'DriveLetter': 'C'}])
        self.assertEqual(r['status'], 'metadata_consistent')
        self.assertFalse(r['approved_for_format'])
        self.assertFalse(r['backup_destination_verified'])

    def test_partition_error_means_review(self):
        r = self.sample(disks=[{'Number': 2}], partitions=[], volumes=[{'DriveLetter': 'C'}],
                        partition_error='Access denied')
        self.assertEqual(r['status'], 'requires_review')
        self.assertTrue(any('Get-Partition falhou' in x for x in r['issues']))

    def test_invalid_or_missing_drive_letters_do_not_become_paths(self):
        r = assess_storage_mapping([{'Number': 0}], [],
                                   [{'DriveLetter': None}, {'DriveLetter': '\\?\\Volume'},
                                    {'DriveLetter': 'C:\\not_a_root'}])
        self.assertEqual(r['letter_mapping'], [])
        self.assertEqual(r['status'], 'requires_review')

    def test_unknown_physical_mapping_still_not_a_safe_backup_destination(self):
        r = self.sample()
        self.assertFalse(r['backup_destination_verified'])


if __name__ == '__main__':
    unittest.main()
