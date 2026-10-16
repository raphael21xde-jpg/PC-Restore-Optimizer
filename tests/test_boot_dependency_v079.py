"""Regression tests for BOOTMGR cross-disk metadata, no hardware changes."""
import unittest

from boot_dependency import assess_bootmgr_disk_dependency


def nt_map(bootmgr_disk, *, correlated=True):
    return {
        'bootmgr_status': 'bootmgr_device_correlated' if correlated else 'bootmgr_device_unverified',
        'volumes': [
            {'bootmgr_device_match': True, 'status': 'observed',
             'disk_numbers': bootmgr_disk, 'letters': [],
             'nt_device': r'\Device\HarddiskVolume5'},
        ]
    }


class BootDependencyTests(unittest.TestCase):
    def test_realistic_bootmgr_disk_one_windows_disk_two(self):
        result = assess_bootmgr_disk_dependency(
            nt_map([1]), {'status': 'unverified', 'boot_disks': [2]})
        self.assertEqual(result['status'], 'separate_disks_reported')
        self.assertEqual(result['windows_disk_numbers'], [2])
        self.assertEqual(result['bootmgr_disk_numbers'], [1])
        self.assertTrue(any('ALERTA DE INICIALIZAÇÃO' in a for a in result['issues']))
        self.assertFalse(result['approved_for_format'])
        self.assertFalse(result['efi_active_verified'])
        self.assertFalse(result['backup_destination_verified'])

    def test_same_disk_never_claims_safe_format(self):
        result = assess_bootmgr_disk_dependency(
            nt_map([2]), {'boot_disks': [2], 'status': 'same_disk_reported'})
        self.assertEqual(result['status'], 'same_disk_reported')
        self.assertFalse(result['approved_for_format'])
        self.assertFalse(result['efi_active_verified'])

    def test_bcd_not_accessible_is_unverified(self):
        result = assess_bootmgr_disk_dependency(nt_map([1], correlated=False),
                                               {'boot_disks': [2]})
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['bootmgr_disk_numbers'], [])
        self.assertFalse(result['approved_for_format'])

    def test_missing_windows_boot_disk_no_claim(self):
        result = assess_bootmgr_disk_dependency(nt_map([1]), {'boot_disks': []})
        self.assertEqual(result['status'], 'unverified')

    def test_multidisk_bootmgr_no_false_certainty(self):
        result = assess_bootmgr_disk_dependency(nt_map([1, 2]), {'boot_disks': [2]})
        self.assertEqual(result['status'], 'unverified')

    def test_multidisk_windows_no_false_certainty(self):
        result = assess_bootmgr_disk_dependency(nt_map([1]), {'boot_disks': [2, 3]})
        self.assertEqual(result['status'], 'unverified')

    def test_invalid_disk_number_no_false_match(self):
        result = assess_bootmgr_disk_dependency(nt_map([True, '1']), {'boot_disks': [2]})
        self.assertEqual(result['status'], 'unverified')

    def test_duplicate_matched_nt_volumes_are_ambiguous(self):
        mapping = nt_map([1])
        mapping['volumes'].append(mapping['volumes'][0].copy())
        result = assess_bootmgr_disk_dependency(mapping, {'boot_disks': [2]})
        self.assertEqual(result['status'], 'unverified')

    def test_missing_data_fails_closed(self):
        result = assess_bootmgr_disk_dependency(None, None)
        self.assertEqual(result['status'], 'unverified')
        self.assertTrue(result['risk_requires_manual_review'])
        self.assertFalse(result['approved_for_format'])


if __name__ == '__main__':
    unittest.main()
