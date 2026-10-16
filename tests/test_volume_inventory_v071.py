import unittest
from unittest.mock import patch
import volume_inventory as vi

V1 = r'\\?\Volume{12345678-1234-1234-1234-123456789abc}' + '\\'
V2 = r'\\?\Volume{12345678-1234-1234-1234-123456789abd}' + '\\'
V3 = r'\\?\Volume{12345678-1234-1234-1234-123456789abe}' + '\\'
V4 = r'\\?\Volume{12345678-1234-1234-1234-123456789abf}' + '\\'


class FakeWindows:
    def __init__(self, entries, failures=()):
        self.entries = {vi.normalize_volume_id(r['volume_id']): r for r in entries}
        self.failures = failures
    def volume_ids(self):
        return list(self.entries)
    def mount_points(self, vol):
        if vol in self.failures:
            raise OSError('volume inaccessible')
        return self.entries[vol]['mount_points']
    def drive_type(self, path):
        for row in self.entries.values():
            if path in row['mount_points'] or path == vi.normalize_volume_id(row['volume_id']):
                return row['drive_type']
        return 0


class VolumeInventoryTests(unittest.TestCase):
    def test_arbitrary_letters_folder_mounts_and_hidden_volume(self):
        source = FakeWindows([
            {'volume_id': V1, 'mount_points': ['Z:\\', 'C:\\Storage\\'], 'drive_type': 3},
            {'volume_id': V2, 'mount_points': [], 'drive_type': 3},
            {'volume_id': V3, 'mount_points': ['X:\\'], 'drive_type': 4},
            {'volume_id': V4, 'mount_points': ['R:\\'], 'drive_type': 2},
        ])
        result = vi.collect_volume_inventory(source)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['volumes']), 4)
        self.assertEqual(vi.letter_scan_roots(result), ['R:\\', 'Z:\\'])
        by_id = {x['volume_id']: x for x in result['volumes']}
        self.assertIn('C:\\Storage\\', by_id[vi.normalize_volume_id(V1)]['scan_roots'])
        self.assertTrue(by_id[vi.normalize_volume_id(V2)]['needs_manual_review'])
        self.assertEqual(by_id[vi.normalize_volume_id(V3)]['scan_roots'], [])

    def test_read_error_must_mark_snapshot_partial(self):
        source = FakeWindows([
            {'volume_id': V1, 'mount_points': ['G:\\'], 'drive_type': 3},
            {'volume_id': V2, 'mount_points': [], 'drive_type': 3},
        ], failures=(vi.normalize_volume_id(V2),))
        result = vi.collect_volume_inventory(source)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(vi.letter_scan_roots(result), ['G:\\'])
        self.assertGreaterEqual(len(result['issues']), 1)

    def test_never_trust_network_unc_or_relative_paths(self):
        for text in ('\\\\server\\share\\', '..\\path\\', 'C:\\..\\Windows\\', '\\\\?\\GLOBALROOT\\'):
            with self.subTest(path=text), self.assertRaises(ValueError):
                vi.normalize_mount_point(text)

    def test_duplicate_ids_or_invalid_entries_mark_partial(self):
        result = vi.summarize_volumes([
            {'volume_id': V1, 'mount_points': ['D:\\'], 'drive_type': 3},
            {'volume_id': V1, 'mount_points': ['E:\\'], 'drive_type': 3},
            {'volume_id': r'\\.\PhysicalDrive0', 'mount_points': ['K:\\'], 'drive_type': 3},
        ])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(vi.letter_scan_roots(result), ['D:\\'])

    def test_volume_ids_are_stable_across_mount_letter_changes(self):
        a = vi.summarize_volumes([{'volume_id': V1, 'mount_points': ['C:\\'], 'drive_type': 3}])
        b = vi.summarize_volumes([{'volume_id': V1, 'mount_points': ['Y:\\'], 'drive_type': 3}])
        self.assertEqual(a['volumes'][0]['volume_id'], b['volumes'][0]['volume_id'])
        self.assertNotEqual(vi.letter_scan_roots(a), vi.letter_scan_roots(b))

    def test_existing_gui_only_offers_confirmed_letter_roots(self):
        from deep_discovery import local_drives
        snapshot = vi.summarize_volumes([
            {'volume_id': V1, 'mount_points': ['P:\\', 'C:\\Mount\\'], 'drive_type': 3},
            {'volume_id': V2, 'mount_points': ['N:\\'], 'drive_type': 4},
            {'volume_id': V3, 'mount_points': [], 'drive_type': 3},
        ])
        with patch('volume_inventory.collect_volume_inventory', return_value=snapshot):
            self.assertEqual(local_drives(), ['P:\\'])

    @unittest.skipUnless(vi.os.name == 'nt', 'Requires native Windows APIs')
    def test_windows_host_can_enumerate_real_mount_metadata_read_only(self):
        snapshot = vi.collect_volume_inventory()
        self.assertTrue(snapshot['volumes'], snapshot['issues'])
        self.assertIn(snapshot['status'], ('ok', 'partial'))
        self.assertTrue(vi.letter_scan_roots(snapshot), snapshot['issues'])

    def test_unsupported_host_is_not_pretended_complete(self):
        if vi.os.name != 'nt':
            result = vi.collect_volume_inventory()
            self.assertEqual(result['status'], 'unsupported')
            self.assertEqual(result['volumes'], [])


if __name__ == '__main__':
    unittest.main()
