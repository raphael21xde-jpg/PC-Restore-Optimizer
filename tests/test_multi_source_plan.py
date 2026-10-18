"""Synthetic, non-destructive tests for multiple selection roots."""
import tempfile
import unittest
from pathlib import Path

from multi_source_plan import prepare_multi_source_preview


class MultiSourcePreviewTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix='pcro-multi-source-')
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.a = self.base / 'volume_a'
        self.b = self.base / 'volume_b'
        self.outside = self.base / 'outside'
        for folder in (self.a, self.b, self.outside):
            folder.mkdir()
        self.first = self.a / 'documento.txt'
        self.second = self.b / 'save.dat'
        self.first.write_bytes(b'arquivo ficticio')
        self.second.write_bytes(b'save ficticio')
        (self.outside / 'secreto.txt').write_bytes(b'nao incluir')

    def test_two_roots_only_plan_without_copy(self):
        plan = prepare_multi_source_preview(
            [str(self.first), str(self.second)], [str(self.a), str(self.b)])
        self.assertEqual(plan.count, 2)
        self.assertEqual(plan.total, self.first.stat().st_size + self.second.stat().st_size)
        self.assertEqual({str(self.first).casefold(), str(self.second).casefold()},
                         {str(Path(task.source)).casefold() for task in plan.files})
        self.assertFalse(any(self.base.rglob('manifest.json')))

    def test_outside_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'fora das raízes'):
            prepare_multi_source_preview(
                [str(self.outside / 'secreto.txt')], [str(self.a), str(self.b)])

    def test_relative_label_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare_multi_source_preview(['Metadados Windows'], [str(self.a)])

    def test_root_itself_cannot_be_selected(self):
        with self.assertRaisesRegex(ValueError, 'fora das raízes'):
            prepare_multi_source_preview([str(self.a)], [str(self.a)])

    def test_outside_choice_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'fora das raízes'):
            prepare_multi_source_preview(
                [str(self.first)], [str(self.a), str(self.b)],
                choices={str(self.outside / 'secreto.txt'): 'skip'})

    def test_missing_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'inexistente'):
            prepare_multi_source_preview([str(self.a / 'apagado.dat')], [str(self.a)])


if __name__ == '__main__':
    unittest.main()
