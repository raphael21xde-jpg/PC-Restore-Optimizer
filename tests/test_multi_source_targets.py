"""Non-destructive multi-source destination preview tests."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets


class MultiSourceTargetPreviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-multi-target-')
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.a, self.b, self.c, self.d = [base / name for name in ('a', 'b', 'c', 'd')]
        for p in (self.a, self.b, self.c, self.d):
            p.mkdir()
        self.f1 = self.a / 'x.txt'
        self.f2 = self.b / 'y.txt'
        self.f1.write_bytes(b'x')
        self.f2.write_bytes(b'y')
        self.plan = prepare_multi_source_preview(
            [str(self.f1), str(self.f2)], [str(self.a), str(self.b)])

    def volume(self, path):
        parts = Path(path).parts
        for letter, folder in [('A:', self.a), ('B:', self.b),
                               ('C:', self.c), ('D:', self.d)]:
            if folder == Path(path) or folder in Path(path).parents:
                return letter
        return 'SEM UNIDADE'

    def preview(self, destinations, *, free=100 * 1024**3):
        return preview_multi_source_targets(
            self.plan, [str(p) for p in destinations],
            volume_lookup=self.volume,
            usage=lambda _: SimpleNamespace(free=free))

    def test_two_separate_destinations_preview_only(self):
        result = self.preview([self.c, self.d])
        self.assertEqual(result['source_volumes'], ['A:', 'B:'])
        self.assertEqual(len(result['destinations']), 2)
        self.assertFalse(result['backup_verified'])
        self.assertFalse(result['ready_for_format'])
        self.assertFalse(result['physical_independence_verified'])
        self.assertTrue(all(x['preflight_status'] == 'requires_review'
                            for x in result['destinations']))

    def test_reject_target_on_second_source_volume(self):
        with self.assertRaisesRegex(ValueError, 'mesma unidade'):
            self.preview([self.b])

    def test_reject_target_on_first_source_volume(self):
        with self.assertRaisesRegex(ValueError, 'mesma unidade'):
            self.preview([self.a])

    def test_reject_insufficient_space(self):
        with self.assertRaisesRegex(ValueError, 'Espaço insuficiente'):
            self.preview([self.c], free=100)

    def test_reject_duplicate_destination(self):
        with self.assertRaisesRegex(ValueError, 'duplicados'):
            self.preview([self.c, self.c])

    def test_reject_unknown_volume(self):
        with self.assertRaisesRegex(ValueError, 'desconhecida'):
            self.preview([self.c.parent])


if __name__ == '__main__':
    unittest.main()
