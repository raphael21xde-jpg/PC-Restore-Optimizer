"""NT volume names are NOT physical-disk identifiers. All tests are mocked."""
import unittest

import nt_volume_mapping as nm


def evidence():
    return {'volumes': [
        {'volume_id': 'vol-f', 'letters': ['F'], 'disk_numbers': [1],
         'status': 'disk_not_listed'},
        {'volume_id': 'vol-efi', 'letters': [], 'disk_numbers': [1],
         'status': 'disk_not_listed'},
        {'volume_id': 'vol-c', 'letters': ['C'], 'disk_numbers': [2],
         'status': 'logical_disk_reported'},
        {'volume_id': 'vol-g', 'letters': ['G'], 'disk_numbers': [4],
         'status': 'virtual_spaces'},
    ]}


def fake_query(guid):
    return {
        'vol-f': '\\Device\\HarddiskVolume13',
        'vol-efi': '\\Device\\HarddiskVolume5',
        'vol-c': '\\Device\\HarddiskVolume2',
        'vol-g': '\\Device\\HarddiskVolume12',
    }[guid]


class NtVolumeMappingTests(unittest.TestCase):
    def test_bootmgr_harddiskvolume5_maps_to_disk_one_not_disk_five(self):
        r = nm.summarize_nt_aliases(
            evidence(), {'nt_volume_devices': ['\\device\\harddiskvolume5']},
            query=fake_query)
        self.assertEqual(r['bootmgr_status'], 'bootmgr_device_correlated')
        self.assertEqual(r['bootmgr_correlated_disks'], [1])
        self.assertEqual([x for x in r['volumes'] if x['bootmgr_device_match']][0]['letters'], [])
        self.assertFalse(r['efi_active_verified'])
        self.assertFalse(r['backup_destination_verified'])
        self.assertFalse(r['approved_for_format'])

    def test_unprivileged_bcd_still_maps_nt_names_but_not_bootmgr(self):
        r = nm.summarize_nt_aliases(evidence(), {'status': 'unavailable'},
                                    query=fake_query)
        self.assertEqual(r['bootmgr_status'], 'bootmgr_unavailable')
        self.assertEqual(len(r['volumes']), 4)
        self.assertTrue(any(x['nt_device'] == '\\Device\\HarddiskVolume5' for x in r['volumes']))
        self.assertEqual(r['bootmgr_correlated_disks'], [])

    def test_access_denied_does_not_invent_device(self):
        def blocked(guid):
            if guid == 'vol-efi':
                raise OSError('access denied')
            return fake_query(guid)
        r = nm.summarize_nt_aliases(
            evidence(), {'nt_volume_devices': ['\\device\\harddiskvolume5']},
            query=blocked)
        self.assertEqual(r['bootmgr_status'], 'bootmgr_device_unverified')
        self.assertTrue(any(x['status'] == 'unavailable' for x in r['volumes']))
        self.assertFalse(r['approved_for_format'])

    def test_duplicated_nt_alias_is_not_trusted_as_unique(self):
        def same(guid):
            return '\\Device\\HarddiskVolume5'
        r = nm.summarize_nt_aliases(
            evidence(), {'nt_volume_devices': ['\\device\\harddiskvolume5']},
            query=same)
        self.assertEqual(r['bootmgr_status'], 'bootmgr_device_unverified')
        self.assertTrue(all(x['status'] == 'ambiguous' for x in r['volumes']))

    def test_unexpected_non_volume_nt_targets_are_rejected(self):
        r = nm.summarize_nt_aliases(evidence(), {},
                                    query=lambda guid: '\\Device\\Harddisk0')
        self.assertTrue(all(x['status'] == 'unavailable' for x in r['volumes']))
        self.assertFalse(r['approved_for_format'])

    def test_enumeration_cap_keeps_failure_closed(self):
        rows = [{'volume_id': str(i), 'letters': [], 'disk_numbers': [1]}
                for i in range(nm.MAX_MAPPINGS + 1)]
        r = nm.summarize_nt_aliases({'volumes': rows}, {}, query=fake_query)
        self.assertEqual(r['volumes'], [])
        self.assertFalse(r['efi_active_verified'])

    def test_current_nt_path_is_not_drive_letter_or_disk_number(self):
        r = nm.summarize_nt_aliases(evidence(), {}, query=fake_query)
        efi = next(x for x in r['volumes'] if x['nt_device'].endswith('Volume5'))
        self.assertEqual(efi['disk_numbers'], [1])
        self.assertNotIn('5', [str(n) for n in efi['disk_numbers']])
        self.assertFalse(efi['letters'])

    def test_non_windows_query_does_not_access_disks(self):
        if nm.os.name != 'nt':
            with self.assertRaises((OSError, ValueError)):
                nm.query_nt_device(r'\\?\Volume{12345678-1234-1234-1234-123456789abc}' + '\\')


if __name__ == '__main__':
    unittest.main()
