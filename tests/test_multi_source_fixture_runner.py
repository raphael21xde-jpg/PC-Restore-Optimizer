"""Non-destructive tests: experimental multi-source executor is sandbox-only."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import backup_core
from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from multi_source_fixture_runner import run_multi_source_fixture_backup
from transfer_engine import choose_strategy


class MultiSourceFixtureRunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-fixture-runner-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.a, self.b, self.target = [self.root / n for n in ('sourceA', 'sourceB', 'targetC')]
        for directory in (self.a, self.b, self.target):
            directory.mkdir()
        self.first, self.second = self.a / 'a.txt', self.b / 'b.sav'
        self.first.write_bytes(b'important A')
        self.second.write_bytes(b'important B')
        self.plan = prepare_multi_source_preview(
            [str(self.first), str(self.second)], [str(self.a), str(self.b)])
        self.preview = preview_multi_source_targets(
            self.plan, [str(self.target)], usage=self.usage, volume_lookup=self.volume)

    def volume(self, path):
        p = Path(path)
        for folder, letter in ((self.a, 'A:'), (self.b, 'B:'), (self.target, 'T:')):
            if p == folder or folder in p.parents:
                return letter
        return 'SEM UNIDADE'

    def usage(self, path):
        return SimpleNamespace(free=100 * 1024 ** 3)

    def run_it(self, root=None):
        return run_multi_source_fixture_backup(
            self.plan, self.preview,
            test_root=str(self.root) if root is None else root,
            volume_lookup=self.volume, usage=self.usage)

    def test_verified_copy_from_two_sources_and_originals_unchanged(self):
        source_hashes = [hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (self.first, self.second)]
        with patch.object(backup_core, 'choose_strategy',
                          lambda src, dst, inventory=None: choose_strategy(src, dst, inventory={})):
            result = self.run_it()
        self.assertTrue(result['backup_verified'])
        self.assertEqual(result['files_verified'], 2)
        self.assertFalse(result['ready_for_format'])
        self.assertFalse(result['installation_authorized'])
        self.assertEqual(source_hashes, [hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in (self.first, self.second)])

    def test_changed_source_blocks_before_creating_backup(self):
        self.second.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'modificada'):
            self.run_it()
        self.assertFalse(list(self.target.iterdir()))

    def test_outside_sandbox_blocks_before_copy(self):
        with self.assertRaisesRegex(ValueError, 'fora da raiz isolada'):
            self.run_it(root=str(self.a))
        self.assertFalse(list(self.target.iterdir()))

    def test_missing_test_root_blocks(self):
        with self.assertRaisesRegex(ValueError, 'raiz de testes'):
            run_multi_source_fixture_backup(
                self.plan, self.preview, test_root=None,
                volume_lookup=self.volume, usage=self.usage)
        self.assertFalse(list(self.target.iterdir()))


if __name__ == '__main__':
    unittest.main()
