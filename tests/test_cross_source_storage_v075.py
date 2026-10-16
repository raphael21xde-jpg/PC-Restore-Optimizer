"""Only simulated evidence, no disk or registry operations."""
import unittest

from storage_cross_source import assess_cross_source_storage


class CrossSourceTests(unittest.TestCase):
    def sample(self):
        disks = [
            {'Number': 2, 'BusType': 'NVMe'},
            {'Number': 3, 'BusType': 'NVMe'},
            {'Number': 4, 'BusType': 'Spaces'},
        ]
        extents = {'status': 'requires_review', 'volumes': [
            {'letters': ['F'], 'disk_numbers': [1], 'status': 'disk_not_listed'},
            {'letters': [], 'disk_numbers': [1], 'status': 'disk_not_listed'},
            {'letters': [], 'disk_numbers': [1], 'status': 'disk_not_listed'},
            {'letters': [], 'disk_numbers': [1], 'status': 'disk_not_listed'},
            {'letters': [], 'disk_numbers': [2], 'status': 'logical_disk_reported'},
            {'letters': ['C'], 'disk_numbers': [2], 'status': 'logical_disk_reported'},
            {'letters': ['D'], 'disk_numbers': [3], 'status': 'logical_disk_reported'},
            {'letters': ['G'], 'disk_numbers': [4], 'status': 'virtual_spaces'},
        ]}
        partitions = {'letter_mapping': [
            {'letter': 'F', 'disk_numbers': [], 'status': 'unverified'},
            {'letter': 'C', 'disk_numbers': [2], 'status': 'reported'},
            {'letter': 'D', 'disk_numbers': [3], 'status': 'reported'},
            {'letter': 'G', 'disk_numbers': [4], 'status': 'reported'},
        ]}
        boot = {'status': 'unverified', 'boot_disks': [2], 'system_disks': []}
        return disks, extents, partitions, boot

    def test_realistic_hidden_volumes_on_unlisted_disk(self):
        r = assess_cross_source_storage(*self.sample())
        self.assertEqual(r['unlisted_extent_disks'], [1])
        self.assertEqual(r['unmounted_volumes_on_unlisted_disks'], {1: 3})
        self.assertTrue(any('Inicialização' in x for x in r['issues']))
        self.assertTrue(any('RISCO DE INICIALIZAÇÃO' in x for x in r['issues']))
        self.assertFalse(r['efi_active_verified'])
        self.assertFalse(r['approved_for_format'])
        self.assertFalse(r['backup_destination_verified'])

    def test_getpartition_disagrees_with_ioctl(self):
        disk, ext, part, boot = self.sample()
        part['letter_mapping'][0]['disk_numbers'] = [2]
        r = assess_cross_source_storage(disk, ext, part, boot)
        self.assertEqual(r['source_conflicts'], [
            {'letter': 'F', 'get_partition': [2], 'ioctl': [1]},
        ])

    def test_metadata_complete_cannot_authorize_format(self):
        disk = [{'Number': 0, 'BusType': 'NVMe'}]
        extent = {'status': 'observed_metadata',
                  'volumes': [{'letters': ['C'], 'disk_numbers': [0],
                               'status': 'logical_disk_reported'}]}
        parts = {'letter_mapping': [{'letter': 'C', 'disk_numbers': [0]}]}
        boot = {'status': 'same_disk_reported', 'boot_disks': [0], 'system_disks': [0]}
        r = assess_cross_source_storage(disk, extent, parts, boot)
        self.assertEqual(r['unlisted_extent_disks'], [])
        self.assertFalse(r['approved_for_format'])
        self.assertFalse(r['efi_active_verified'])

    def test_unavailable_extents_are_unknown_not_absent(self):
        r = assess_cross_source_storage(
            [{'Number': 0}], {'status': 'unsupported', 'volumes': []},
            {'letter_mapping': []}, {'status': 'unverified'})
        self.assertEqual(r['unlisted_extent_disks'], [])
        self.assertTrue(any('não foi possível' in x.lower() for x in r['issues']))
        self.assertFalse(r['backup_destination_verified'])

    def test_multidisk_extent_tracks_all_disk_numbers(self):
        r = assess_cross_source_storage(
            [{'Number': 2}], {'status': 'requires_review', 'volumes': [
                {'letters': ['X'], 'disk_numbers': [1, 2], 'status': 'multi_disk'}
            ]}, {'letter_mapping': []}, {'status': 'unverified'})
        self.assertEqual(r['unlisted_extent_disks'], [1])
        self.assertFalse(r['approved_for_format'])

    def test_integer_only_disk_indices(self):
        r = assess_cross_source_storage(
            [{'Number': True}], {'status': 'requires_review', 'volumes': [
                {'letters': ['F'], 'disk_numbers': [1, '0', True], 'status': 'disk_not_listed'}
            ]}, {'letter_mapping': []}, {'status': 'unverified'})
        self.assertEqual(r['unlisted_extent_disks'], [1])


if __name__ == '__main__':
    unittest.main()
