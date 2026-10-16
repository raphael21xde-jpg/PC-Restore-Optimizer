"""Non-destructive simulated volume IOCTL scenarios."""
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import storage_extents_diagnostic as sd
from volume_inventory import summarize_volumes

V1 = r'\\?\Volume{12345678-1234-1234-1234-123456789abc}' + '\\'
V2 = r'\\?\Volume{12345678-1234-1234-1234-123456789abd}' + '\\'
V3 = r'\\?\Volume{12345678-1234-1234-1234-123456789abe}' + '\\'
V4 = r'\\?\Volume{12345678-1234-1234-1234-123456789abf}' + '\\'


def volume_snapshot():
    return summarize_volumes([
        {'volume_id': V1, 'mount_points': ['F:\\'], 'drive_type': 3},
        {'volume_id': V2, 'mount_points': ['G:\\'], 'drive_type': 3},
        {'volume_id': V3, 'mount_points': ['C:\\'], 'drive_type': 3},
        {'volume_id': V4, 'mount_points': [], 'drive_type': 3},
    ])


def mapped(id_, *disks):
    return {'device_id': id_, 'status': 'mapped',
            'extents': [{'disk_number': number,
                         'starting_offset': 0, 'extent_length': 4096} for number in disks]}


class PhysicalExtentSafetyTests(unittest.TestCase):
    def test_missing_dynamic_disk_is_reported_not_invented(self):
        r = sd.describe_extents(volume_snapshot(),
                                [mapped(V1, 1), mapped(V2, 4), mapped(V3, 2)],
                                [{'Number': 2, 'BusType': 'NVMe'},
                                 {'Number': 4, 'BusType': 'Spaces'}])
        volumes = {tuple(v['letters']): v for v in r['volumes']}
        self.assertEqual(volumes[('F',)]['disk_numbers'], [1])
        self.assertEqual(volumes[('F',)]['status'], 'disk_not_listed')
        self.assertEqual(volumes[('G',)]['status'], 'virtual_spaces')
        self.assertEqual(volumes[('C',)]['status'], 'logical_disk_reported')
        self.assertEqual(volumes[()]['status'], 'unknown')
        self.assertFalse(r['backup_destination_verified'])
        self.assertFalse(r['approved_for_format'])

    def test_multi_disk_volume_stays_ambiguous(self):
        snapshot = summarize_volumes([
            {'volume_id': V1, 'mount_points': ['X:\\'], 'drive_type': 3},
        ])
        r = sd.describe_extents(snapshot, [mapped(V1, 3, 4)],
                                [{'Number': 3, 'BusType': 'NVMe'},
                                 {'Number': 4, 'BusType': 'NVMe'}])
        self.assertEqual(r['volumes'][0]['status'], 'multi_disk')

    def test_failed_ioctl_is_unknown(self):
        rows = [{'device_id': V1, 'status': 'unmapped', 'extents': [], 'error': 'Access denied'}]
        result = sd.describe_extents(volume_snapshot(), rows, [])
        self.assertEqual(result['volumes'][0]['status'], 'unknown')
        self.assertTrue(result['issues'])

    def test_read_only_runner_receives_guid_and_has_timeout(self):
        snapshot = summarize_volumes([{'volume_id': V1, 'mount_points': ['F:\\'], 'drive_type': 3}])
        captured = {}
        def runner(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            return SimpleNamespace(returncode=0, stdout=json.dumps([mapped(V1, 1)]), stderr='')
        with patch.object(sd, 'os', SimpleNamespace(name='nt')):
            result = sd.collect_extent_mapping([], snapshot=snapshot, runner=runner, timeout=3)
        self.assertEqual(result['volumes'][0]['status'], 'disk_not_listed')
        self.assertEqual(captured['kwargs']['timeout'], 3)
        self.assertEqual(json.loads(captured['kwargs']['input'])[0]['device_id'], V1.upper().replace('VOLUME', 'Volume'))
        self.assertTrue(captured['command'][1].endswith('volume_extents.py'))

    def test_timeout_does_not_turn_unknown_into_safe(self):
        snapshot = summarize_volumes([{'volume_id': V1, 'mount_points': ['F:\\'], 'drive_type': 3}])
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 1)
        with patch.object(sd, 'os', SimpleNamespace(name='nt')):
            result = sd.collect_extent_mapping([], snapshot=snapshot, runner=runner, timeout=1)
        self.assertEqual(result['status'], 'requires_review')
        self.assertFalse(result['approved_for_format'])
        self.assertEqual(result['volumes'][0]['status'], 'unknown')

    def test_invalid_duplicate_response_is_ignored(self):
        snapshot = summarize_volumes([{'volume_id': V1, 'mount_points': ['F:\\'], 'drive_type': 3}])
        result = sd.describe_extents(snapshot, [
            {'device_id': r'\\.\PhysicalDrive0', 'status': 'mapped', 'extents': []},
            mapped(V1, 3), mapped(V1, 4),
        ], [{'Number': 3, 'BusType': 'NVMe'}])
        self.assertEqual(result['volumes'][0]['disk_numbers'], [3])
        self.assertEqual(result['status'], 'requires_review')

    def test_unsupported_host_does_not_probe_storage(self):
        if sd.os.name != 'nt':
            result = sd.collect_extent_mapping([], snapshot=volume_snapshot())
            self.assertEqual(result['status'], 'requires_review')
            self.assertTrue(all(v['status'] == 'unknown' for v in result['volumes']))


if __name__ == '__main__':
    unittest.main()
