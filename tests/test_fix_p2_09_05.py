"""FIX-P2-09-05: ``st_file_attributes`` set to None must not break the check.

Only fake ``os.lstat`` results and synthetic files inside TemporaryDirectory.
No real disk, command, PowerShell, WMI or registry is used, and no tkinter.
"""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import selective_recovery  # noqa: E402
import multi_source_executor as executor  # noqa: E402
from selective_recovery import REPARSE_FLAG, _any_reparse_ancestor  # noqa: E402
from test_real_copy_flow_p2_09 import Base  # noqa: E402

REAL_LSTAT = os.lstat


def fake_dir_stat(attributes):
    return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755,
                           st_file_attributes=attributes)


class WithAttributes:
    """Real lstat result, but with a chosen ``st_file_attributes``."""

    def __init__(self, info, attributes):
        self._info = info
        self.st_file_attributes = attributes

    def __getattr__(self, name):
        return getattr(self._info, name)


class AnyReparseAncestorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-fix0905-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'pasta'
        self.root.mkdir()

    def test_none_attributes_are_not_a_reparse_point(self):
        with patch.object(selective_recovery.os, 'lstat',
                          lambda _p: fake_dir_stat(None)):
            self.assertIsNone(_any_reparse_ancestor(self.root))

    def test_reparse_flag_is_refused(self):
        with patch.object(selective_recovery.os, 'lstat',
                          lambda _p: fake_dir_stat(REPARSE_FLAG)):
            with self.assertRaisesRegex(ValueError, 'Link/junção proibido'):
                _any_reparse_ancestor(self.root)


class OsWithNoneAttributes:
    """Stand-in for ``os`` seen only by selective_recovery (other modules
    keep the real one): ``lstat`` answers ``st_file_attributes=None``."""

    def __getattr__(self, name):
        return getattr(os, name)

    @staticmethod
    def lstat(path, *args, **kwargs):
        return WithAttributes(REAL_LSTAT(path, *args, **kwargs), None)


class RealModeNoneAttributesTests(Base):
    def test_preview_real_execution_accepts_none_attributes(self):
        preview = self.preview()
        with self.temp_target(), patch.object(selective_recovery, 'os',
                                              OsWithNoneAttributes()):
            info = executor.preview_real_execution(
                self.plan, preview, **self.kwargs())
        self.assertEqual(info['copies'], 2)
        self.assertNothingWritten()


if __name__ == '__main__':
    unittest.main()
