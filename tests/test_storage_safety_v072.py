import unittest

from storage_safety import assess_boot_layout


class CrossDiskBootSafetyTests(unittest.TestCase):
    def test_realistic_cross_disk_example_is_flagged(self):
        result = assess_boot_layout(
            [{'Number': 1}, {'Number': 2}],
            [
                {'DiskNumber': 1, 'PartitionNumber': 1, 'IsSystem': True, 'IsBoot': False},
                {'DiskNumber': 2, 'PartitionNumber': 1, 'IsSystem': False, 'IsBoot': True},
            ],
        )
        self.assertEqual(result['status'], 'cross_disk')
        self.assertEqual(result['system_disks'], [1])
        self.assertEqual(result['boot_disks'], [2])
        self.assertFalse(result['approved_for_format'])

    def test_same_disk_never_authorizes_format(self):
        result = assess_boot_layout([], [
            {'DiskNumber': 0, 'IsSystem': True, 'IsBoot': False},
            {'DiskNumber': 0, 'IsSystem': False, 'IsBoot': True},
        ])
        self.assertEqual(result['status'], 'same_disk_reported')
        self.assertFalse(result['approved_for_format'])

    def test_ambiguous_or_missing_data_does_not_claim_safe(self):
        for disks, parts in [([], []), ([{'Number': 0, 'IsBoot': True}], []),
                             ([], [{'DiskNumber': None, 'IsSystem': True}])]:
            with self.subTest(disks=disks, parts=parts):
                x = assess_boot_layout(disks, parts)
                self.assertEqual(x['status'], 'unverified')
                self.assertFalse(x['approved_for_format'])

    def test_fallback_to_disk_metadata(self):
        result = assess_boot_layout(
            [{'Number': 3, 'IsBoot': True}, {'Number': 6, 'IsSystem': True}],
            [],
        )
        self.assertEqual(result['status'], 'cross_disk')

    def test_bad_disk_numbers_cannot_hide_missing_evidence(self):
        result = assess_boot_layout([], [
            {'DiskNumber': '1', 'IsSystem': True},
            {'DiskNumber': '2', 'IsBoot': True},
        ])
        self.assertEqual(result['status'], 'unverified')


if __name__ == '__main__':
    unittest.main()
