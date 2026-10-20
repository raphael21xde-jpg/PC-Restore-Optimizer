"""Non-destructive pre-execution recheck using synthetic files only."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from multi_source_recheck import recheck_multi_source_preview


class MultiSourceRecheckTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix='pcro-recheck-')
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.a = self.root / 'source_A'
        self.b = self.root / 'source_B'
        self.target = self.root / 'destination'
        for p in (self.a, self.b, self.target):
            p.mkdir()
        self.file_a = self.a / 'a.txt'
        self.file_b = self.b / 'b.txt'
        self.file_a.write_bytes(b'AAA')
        self.file_b.write_bytes(b'BBB')
        self.plan = prepare_multi_source_preview(
            [str(self.file_a), str(self.file_b)], [str(self.a), str(self.b)])
        self.volumes = {'source_A': 'A:', 'source_B': 'B:', 'destination': 'D:'}
        self.preview = self._preview()

    def _volume(self, path):
        p = Path(path)
        for folder in (self.a, self.b, self.target):
            if p == folder or folder in p.parents:
                return self.volumes[folder.name]
        return 'SEM UNIDADE'

    def _usage(self, _):
        return SimpleNamespace(free=100 * 1024**3)

    def _preview(self):
        return preview_multi_source_targets(
            self.plan, [str(self.target)], usage=self._usage,
            volume_lookup=self._volume)

    def recheck(self):
        return recheck_multi_source_preview(
            self.plan, self.preview, usage=self._usage,
            volume_lookup=self._volume)

    def test_unchanged_preview_remains_review_only(self):
        result = self.recheck()
        self.assertFalse(result['backup_verified'])
        self.assertFalse(result['ready_for_format'])
        self.assertFalse(result['installation_authorized'])
        self.assertEqual(result['source_volumes'], ['A:', 'B:'])

    def test_source_change_rejected(self):
        self.file_b.write_bytes(b'alterado')
        with self.assertRaisesRegex(ValueError, 'modificada'):
            self.recheck()

    def test_missing_source_rejected(self):
        self.file_a.unlink()
        with self.assertRaisesRegex(ValueError, 'desapareceu'):
            self.recheck()

    def test_source_volume_changed_rejected(self):
        self.volumes['source_B'] = 'E:'
        with self.assertRaisesRegex(ValueError, 'Unidades de origem mudaram'):
            self.recheck()

    def test_target_now_on_source_volume_rejected(self):
        self.volumes['destination'] = 'B:'
        with self.assertRaisesRegex(ValueError, 'mesma unidade'):
            self.recheck()

    def test_forged_approval_rejected(self):
        self.preview['installation_authorized'] = True
        with self.assertRaisesRegex(ValueError, 'não pode autorizar'):
            self.recheck()


if __name__ == '__main__':
    unittest.main()
