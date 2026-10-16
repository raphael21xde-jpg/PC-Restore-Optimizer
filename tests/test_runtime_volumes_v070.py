import unittest
from unittest.mock import patch
import runtime_volumes

class DriveTests(unittest.TestCase):
    def test_no_assumed_drives_on_non_windows(self):
        with patch.object(runtime_volumes.os, "name", "posix"):
            self.assertEqual(runtime_volumes.discover_drive_letters(), ())
    def test_destination_requires_user_choice(self):
        for letters in [(), ("C",), ("C", "D", "F", "G"), ("Z",)]:
            self.assertEqual(runtime_volumes.choose_backup_destination(letters), "")
if __name__ == "__main__":
    unittest.main()
