"""Directory identity checks for backup destination swaps (temporary fixtures only)."""
import tempfile
import unittest
from pathlib import Path

from backup_destination_guard import (
    destination_ancestry_identity, require_unchanged_destination_ancestry,
)


class MultiSourceAncestryIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-ancestry-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'backup'
        self.root.mkdir()
        self.directory = self.root / 'nested'
        self.directory.mkdir()
        self.target = self.directory / 'data.bin'

    def test_stable_ancestry_passes(self):
        snapshot = destination_ancestry_identity(self.root, self.target)
        require_unchanged_destination_ancestry(self.root, self.target, snapshot)

    def test_replaced_directory_is_rejected(self):
        snapshot = destination_ancestry_identity(self.root, self.target)
        old = self.root / 'old-nested'
        self.directory.rename(old)
        self.directory.mkdir()
        with self.assertRaisesRegex(ValueError, 'substituído'):
            require_unchanged_destination_ancestry(self.root, self.target, snapshot)
        self.assertFalse(self.target.exists())

    def test_missing_directory_fails_closed(self):
        snapshot = destination_ancestry_identity(self.root, self.target)
        self.directory.rmdir()
        with self.assertRaises((OSError, ValueError)):
            require_unchanged_destination_ancestry(self.root, self.target, snapshot)


if __name__ == '__main__':
    unittest.main()
