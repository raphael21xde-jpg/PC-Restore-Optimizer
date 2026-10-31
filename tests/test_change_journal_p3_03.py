"""P3-03 fatia 1: diário de alterações, desfazer um item e desfazer tudo.

Tudo com TemporaryDirectory e adaptadores falsos que guardam o valor em
memória. Nenhum comando real, registro ou WMI é usado.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import change_journal as cj  # noqa: E402


class FakeAdapter:
    """Ajuste falso: o valor fica em memória e cada chamada é registrada."""

    def __init__(self, calls, initial=None, label='ajuste de teste'):
        self.calls = calls
        self.values = dict(initial or {})
        self.label = label
        self.ignore_apply = set()      # chaves cujo apply "não pega"
        self.ignore_revert = set()     # chaves cujo revert "não pega"
        self.raise_apply = set()

    def read(self, key):
        self.calls.append(('read', key))
        return self.values.get(key)

    def apply(self, key, value):
        self.calls.append(('apply', key, value))
        if key in self.raise_apply:
            raise OSError('falha simulada')
        if key not in self.ignore_apply:
            self.values[key] = value

    def revert(self, key, value):
        self.calls.append(('revert', key, value))
        if key not in self.ignore_revert:
            self.values[key] = value


class RestorePoint:
    def __init__(self, calls, ok=True, raises=False):
        self.calls = calls
        self.ok = ok
        self.raises = raises
        self.descriptions = []

    def __call__(self, description):
        self.calls.append(('restore_point', description))
        self.descriptions.append(description)
        if self.raises:
            raise OSError('sem ponto de restauração')
        return self.ok


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / 'diario.json'
        self.calls = []
        self.adapter = FakeAdapter(self.calls, {'a': 1, 'b': 'equilibrado', 'c': False})
        self.rp = RestorePoint(self.calls)

    def tearDown(self):
        self._tmp.cleanup()

    def journal(self, rp=None, adapters=None):
        return cj.ChangeJournal(self.path, adapters or {'energia': self.adapter}, rp or self.rp)

    def statuses(self, j):
        return [e['status'] for e in j.entries()]

    def no_tmp_left(self):
        return [p.name for p in self.dir.iterdir() if p.name.endswith('.tmp')]


class ApplyAndUndoTests(Base):
    def test_apply_and_undo_single_item(self):
        j = self.journal()
        ids = j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.assertEqual(len(ids), 1)
        self.assertEqual(self.adapter.values['b'], 'alto')
        entry = j.entries()[0]
        self.assertEqual((entry['before'], entry['after'], entry['status']), ('equilibrado', 'alto', 'applied'))
        ok, reason = j.undo(ids[0])
        self.assertTrue(ok, reason)
        self.assertEqual(self.adapter.values['b'], 'equilibrado')
        self.assertEqual(self.statuses(j), ['reverted'])

    def test_undo_all_reverse_order(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'},
                       {'kind': 'energia', 'key': 'c', 'after': True}])
        self.calls.clear()
        done, pending, reason = j.undo_all()
        self.assertEqual((len(done), pending, reason), (3, [], ''))
        reverts = [c[1] for c in self.calls if c[0] == 'revert']
        self.assertEqual(reverts, ['c', 'b', 'a'])
        self.assertEqual(self.adapter.values, {'a': 1, 'b': 'equilibrado', 'c': False})
        self.assertEqual(self.statuses(j), ['reverted'] * 3)

    def test_restore_point_once_per_batch_before_first_apply(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2},
                       {'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        names = [c[0] for c in self.calls]
        self.assertEqual(names.count('restore_point'), 1)
        self.assertLess(names.index('restore_point'), names.index('apply'))
        j.apply_batch([{'kind': 'energia', 'key': 'c', 'after': True}])
        self.assertEqual([c[0] for c in self.calls].count('restore_point'), 2)

    def test_restore_point_failure_refuses_batch(self):
        for rp in (RestorePoint(self.calls, ok=False), RestorePoint(self.calls, raises=True)):
            with self.subTest(ok=rp.ok, raises=rp.raises):
                self.calls.clear()
                j = self.journal(rp=rp)
                with self.assertRaises(cj.BatchRefused):
                    j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
                self.assertNotIn('apply', [c[0] for c in self.calls])
                self.assertEqual(self.adapter.values['a'], 1)
                self.assertNotIn('applied', self.statuses(j))
                if self.path.exists():
                    data = json.loads(self.path.read_text(encoding='utf-8'))
                    self.assertNotIn('applied', [e['status'] for e in data['entries']])

    def test_unconfirmed_read_mid_batch_rolls_back_previous(self):
        self.adapter.ignore_apply.add('b')
        j = self.journal()
        with self.assertRaises(cj.BatchRefused):
            j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2},
                           {'kind': 'energia', 'key': 'b', 'after': 'alto'},
                           {'kind': 'energia', 'key': 'c', 'after': True}])
        self.assertEqual(self.adapter.values, {'a': 1, 'b': 'equilibrado', 'c': False})
        self.assertNotIn(('apply', 'c', True), self.calls)
        self.assertIn(('revert', 'a', 1), self.calls)
        self.assertEqual(self.statuses(j), ['failed', 'failed'])

    def test_apply_exception_rolls_back(self):
        self.adapter.raise_apply.add('b')
        j = self.journal()
        with self.assertRaises(cj.BatchRefused):
            j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2},
                           {'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.assertEqual(self.adapter.values['a'], 1)
        self.assertEqual(self.statuses(j), ['failed', 'failed'])

    def test_rollback_that_does_not_confirm_becomes_unknown_and_blocks(self):
        self.adapter.ignore_apply.add('b')
        self.adapter.ignore_revert.add('a')
        j = self.journal()
        with self.assertRaises(cj.BatchRefused):
            j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2},
                           {'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.assertEqual(self.statuses(j), ['unknown', 'failed'])
        with self.assertRaises(cj.BatchRefused):
            j.apply_batch([{'kind': 'energia', 'key': 'c', 'after': True}])

    def test_undo_refuses_when_value_changed_outside(self):
        j = self.journal()
        ids = j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.adapter.values['b'] = 'economia'  # outro programa mudou
        self.calls.clear()
        ok, reason = j.undo(ids[0])
        self.assertFalse(ok)
        self.assertIn('outro programa', reason)
        self.assertNotIn('revert', [c[0] for c in self.calls])
        self.assertEqual(self.adapter.values['b'], 'economia')
        self.assertEqual(self.statuses(j), ['applied'])

    def test_undo_unknown_id_or_not_applied(self):
        j = self.journal()
        ids = j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        self.assertFalse(j.undo('999')[0])
        self.assertTrue(j.undo(ids[0])[0])
        ok, reason = j.undo(ids[0])
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_undo_all_stops_at_first_failure(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        j.apply_batch([{'kind': 'energia', 'key': 'c', 'after': True}])
        self.adapter.values['b'] = 'economia'
        self.calls.clear()
        done, pending, reason = j.undo_all()
        self.assertEqual(len(done), 1)
        self.assertEqual(len(pending), 2)
        self.assertIn('outro programa', reason)
        self.assertEqual([c[1] for c in self.calls if c[0] == 'revert'], ['c'])
        self.assertEqual(self.adapter.values['a'], 2)
        self.assertEqual(self.statuses(j), ['applied', 'applied', 'reverted'])

    def test_undo_all_empty(self):
        j = self.journal()
        self.assertEqual(j.undo_all(), ([], [], ''))


class ValidationTests(Base):
    def test_refuses_unknown_kind_path_values_and_non_simple(self):
        bad_batches = [
            [{'kind': 'desconhecido', 'key': 'a', 'after': 2}],
            [{'kind': 'energia', 'key': 'a', 'after': 'C:\\Users\\fulano\\x'}],
            [{'kind': 'energia', 'key': 'a', 'after': '/home/fulano'}],
            [{'kind': 'energia', 'key': 'a', 'after': '%APPDATA%'}],
            [{'kind': 'energia', 'key': 'a', 'after': [1, 2]}],
            [{'kind': 'energia', 'key': 'a', 'after': {'x': 1}}],
            [{'kind': 'energia', 'key': 'a', 'after': float('nan')}],
            [{'kind': 'energia', 'key': 'C:\\Windows', 'after': 1}],
            [{'kind': 'energia', 'key': 'a'}],
            [{'kind': 'energia', 'key': 'a', 'after': 2, 'extra': 1}],
            [],
            'nao e lista',
        ]
        j = self.journal()
        for batch in bad_batches:
            with self.subTest(batch=batch):
                self.calls.clear()
                with self.assertRaises(cj.BatchRefused):
                    j.apply_batch(batch)
                self.assertEqual(self.calls, [])
        self.assertEqual(j.entries(), [])
        self.assertFalse(self.path.exists())

    def test_before_value_with_path_refused(self):
        self.adapter.values['a'] = 'D:\\Jogos'
        j = self.journal()
        with self.assertRaises(cj.BatchRefused):
            j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 'x'}])
        self.assertNotIn('apply', [c[0] for c in self.calls])
        self.assertNotIn('D:\\Jogos', self.path.read_text(encoding='utf-8') if self.path.exists() else '')

    def test_bool_and_int_are_not_confused(self):
        self.adapter.values['a'] = 1
        j = self.journal()
        ids = j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': True}])
        self.adapter.values['a'] = 1  # mesmo "==", tipo diferente
        self.assertFalse(j.undo(ids[0])[0])

    def test_adapter_without_methods_refused(self):
        with self.assertRaises(cj.JournalError):
            cj.ChangeJournal(self.path, {'energia': object()}, self.rp)
        with self.assertRaises(cj.JournalError):
            cj.ChangeJournal(self.path, {'energia': self.adapter}, None)


class FileTests(Base):
    def _write(self, text):
        self.path.write_text(text, encoding='utf-8')

    def test_corrupted_or_wrong_schema_blocks(self):
        cases = [
            'isto nao e json',
            json.dumps({'schema': 'outro', 'entries': []}),
            json.dumps({'schema': 'pcro-journal-1', 'entries': 'x'}),
            json.dumps({'schema': 'pcro-journal-1', 'entries': [{'id': '1'}]}),
            json.dumps([1, 2]),
        ]
        for text in cases:
            with self.subTest(text=text):
                self._write(text)
                with self.assertRaises(cj.JournalError):
                    self.journal()
                self.assertEqual(self.path.read_text(encoding='utf-8'), text)
                self.assertEqual(self.calls, [])

    def test_symlink_journal_blocks(self):
        real = self.dir / 'real.json'
        real.write_text(json.dumps({'schema': 'pcro-journal-1', 'entries': []}), encoding='utf-8')
        try:
            os.symlink(real, self.path)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'o sistema não deixou criar link: {exc}')
        before = real.read_text(encoding='utf-8')
        with self.assertRaises(cj.JournalError):
            self.journal()
        self.assertEqual(real.read_text(encoding='utf-8'), before)

    def test_save_refuses_when_target_became_link(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        real = self.dir / 'outro.json'
        real.write_text('intocado', encoding='utf-8')
        self.path.unlink()
        try:
            os.symlink(real, self.path)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'o sistema não deixou criar link: {exc}')
        self.calls.clear()
        with self.assertRaises(cj.JournalError):
            j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.assertEqual(real.read_text(encoding='utf-8'), 'intocado')
        self.assertNotIn('apply', [c[0] for c in self.calls])
        self.assertEqual(self.no_tmp_left(), [])

    def test_reopen_keeps_history_and_no_tmp(self):
        j = self.journal()
        ids = j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        j.undo(ids[0])
        j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        j2 = self.journal()
        self.assertEqual(j2.entries(), j.entries())
        self.assertEqual(self.statuses(j2), ['reverted', 'applied'])
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(data['schema'], 'pcro-journal-1')
        self.assertEqual(self.no_tmp_left(), [])
        ids2 = j2.apply_batch([{'kind': 'energia', 'key': 'c', 'after': True}])
        self.assertNotIn(ids2[0], ids)
        self.assertEqual(len(j2.entries()), 3)

    def test_entries_are_read_only_copies(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        j.entries()[0]['status'] = 'reverted'
        self.assertEqual(self.statuses(j), ['applied'])


class RecoveryTests(Base):
    def _interrupted(self, current):
        """Simula queda depois de gravar 'prepared' (o apply pode ou não ter pegado)."""
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['entries'][0]['status'] = 'prepared'
        self.path.write_text(json.dumps(data), encoding='utf-8')
        self.adapter.values['b'] = current
        return self.journal()

    def test_prepared_blocks_new_batch_until_recovered(self):
        j = self._interrupted('alto')
        self.calls.clear()
        with self.assertRaises(cj.BatchRefused):
            j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        self.assertEqual(self.calls, [])

    def test_recover_three_outcomes(self):
        for current, expected in (('equilibrado', 'failed'), ('alto', 'applied'), ('economia', 'unknown')):
            with self.subTest(current=current):
                self.path.unlink(missing_ok=True)
                self.calls.clear()
                j = self._interrupted(current)
                self.calls.clear()
                result = j.recover_interrupted()
                self.assertEqual([r[1] for r in result], [expected])
                self.assertNotIn('apply', [c[0] for c in self.calls])
                self.assertNotIn('revert', [c[0] for c in self.calls])
                self.assertEqual(self.statuses(self.journal()), [expected])
                if expected == 'unknown':
                    with self.assertRaises(cj.BatchRefused):
                        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
                else:
                    j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])


class TextAndModuleTests(Base):
    def test_summary_lines_portuguese_without_paths(self):
        j = self.journal()
        self.assertEqual(j.summary_lines(), ['Nenhuma alteração registrada.'])
        ids = j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        j.undo(ids[0])
        lines = j.summary_lines()
        text = '\n'.join(lines)
        self.assertIn('ajuste de teste', text)
        self.assertIn('desfeita', text)
        self.assertIn('aplicada', text)
        for bad in (str(self.dir), '\\', '/', 'applied', 'reverted', 'energia'):
            self.assertNotIn(bad, text)

    def test_error_messages_without_paths(self):
        self.path.write_text('lixo', encoding='utf-8')
        with self.assertRaises(cj.JournalError) as ctx:
            self.journal()
        self.assertNotIn(str(self.dir), str(ctx.exception))

    def test_module_imports_no_subprocess_tk_winreg(self):
        tree = ast.parse((ROOT / 'change_journal.py').read_text(encoding='utf-8'))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or '').split('.')[0])
        for forbidden in ('subprocess', 'tkinter', 'winreg', 'ctypes', 'shutil'):
            self.assertNotIn(forbidden, names)


if __name__ == '__main__':
    unittest.main()
