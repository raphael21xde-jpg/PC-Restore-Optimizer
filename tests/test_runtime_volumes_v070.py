import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import runtime_volumes


class DriveTests(unittest.TestCase):
    def test_no_assumed_drives_on_non_windows(self):
        with patch.object(runtime_volumes.os, 'name', 'posix'):
            self.assertEqual(runtime_volumes.discover_drive_letters(), ())

    def test_windows_drive_bitmask_is_dynamic(self):
        drive_mask = (1 << 2) | (1 << 6) | (1 << 25)
        windll = SimpleNamespace(kernel32=SimpleNamespace(GetLogicalDrives=Mock(return_value=drive_mask)))
        with patch.object(runtime_volumes.os, 'name', 'nt'), patch.object(runtime_volumes.ctypes, 'windll', windll, create=True):
            self.assertEqual(runtime_volumes.discover_drive_letters(), ('C', 'G', 'Z'))

    def test_windows_api_failure_has_safe_fallback(self):
        windll = SimpleNamespace(kernel32=SimpleNamespace(GetLogicalDrives=Mock(side_effect=OSError('denied'))))
        with patch.object(runtime_volumes.os, 'name', 'nt'), patch.object(runtime_volumes.ctypes, 'windll', windll, create=True):
            self.assertEqual(runtime_volumes.discover_drive_letters(), ())

    def test_destination_requires_user_choice(self):
        for letters in [(), ('C',), ('C', 'D', 'F', 'G'), ('Z',)]:
            self.assertEqual(runtime_volumes.choose_backup_destination(letters), '')


if __name__ == '__main__':
    unittest.main()
