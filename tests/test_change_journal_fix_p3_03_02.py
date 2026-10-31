"""FIX-P3-03-02: ressalvas da revisão da PR #115 (issue #116) no diário de alterações.

Tudo com TemporaryDirectory e os adaptadores falsos de test_change_journal_p3_03.
Nenhum comando real, registro ou WMI é usado.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import change_journal as cj  # noqa: E402
from tests.test_change_journal_p3_03 import FakeAdapter, RestorePoint  # noqa: E402

STALE = ('O diário de alterações foi alterado por outra janela do app; '
         'feche e abra de novo. Nada foi gravado.')


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

    def journal(self, adapter=None, rp=None):
        return cj.ChangeJournal(self.path, {'energia': adapter or self.adapter}, rp or self.rp)

    def disk_entries(self):
        return json.loads(self.path.read_text(encoding='utf-8'))['entries']


class TwoWindowsTest(Base):
    """(a) Duas instâncias (duas janelas do app) no mesmo arquivo."""

    def test_second_window_refuses_and_keeps_first_entry(self):
        a = self.journal()
        calls_b = []
        adapter_b = FakeAdapter(calls_b, {'a': 1, 'b': 'equilibrado', 'c': False})
        rp_b = RestorePoint(calls_b)
        b = self.journal(adapter_b, rp_b)  # abriu antes de A gravar
        self.assertEqual(a.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}]), ['1'])
        before = self.path.read_bytes()

        with self.assertRaises(cj.JournalError) as ctx:
            b.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.assertEqual(str(ctx.exception), STALE)
        self.assertEqual(calls_b, [])  # nem ponto de restauração nem adaptador
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([(e['id'], e['key'], e['status']) for e in self.disk_entries()],
                         [('1', 'a', 'applied')])

        with self.assertRaises(cj.JournalError) as ctx:
            b.undo('1')
        self.assertEqual(str(ctx.exception), STALE)
        with self.assertRaises(cj.JournalError):
            b.undo_all()
        with self.assertRaises(cj.JournalError):
            b.recover_interrupted()
        self.assertEqual(calls_b, [])
        self.assertEqual(self.path.read_bytes(), before)

        c = self.journal()  # janela reaberta vê o que A gravou
        self.assertEqual([e['id'] for e in c.entries()], ['1'])
        self.assertEqual(c.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}]), ['2'])
        self.assertEqual([e['key'] for e in self.disk_entries()], ['a', 'b'])

    def test_same_instance_keeps_working_after_its_own_saves(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.assertEqual(j.undo_all(), (['2', '1'], [], ''))

    def test_second_window_on_new_file_refuses(self):
        # Os dois abriram sem arquivo; A criou o arquivo.
        a = self.journal()
        b = self.journal()
        a.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        self.calls.clear()
        with self.assertRaises(cj.JournalError):
            b.apply_batch([{'kind': 'energia', 'key': 'c', 'after': True}])
        self.assertEqual(self.calls, [])
        self.assertEqual([e['key'] for e in self.disk_entries()], ['a'])


class ChangedOutsideTest(Base):
    """(b) Arquivo apagado ou trocado por fora entre gravações."""

    def test_deleted_between_saves_refuses_and_does_not_recreate(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        self.path.unlink()
        self.calls.clear()
        with self.assertRaises(cj.JournalError) as ctx:
            j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.assertEqual(str(ctx.exception), STALE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.calls, [])
        with self.assertRaises(cj.JournalError):
            j.undo('1')
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.dir.iterdir()), [])  # nem temporário sobrou

    def test_replaced_between_saves_refuses_and_does_not_overwrite(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        other = json.dumps({'schema': cj.SCHEMA, 'entries': []}).encode('utf-8')
        self.path.write_bytes(other)
        self.calls.clear()
        with self.assertRaises(cj.JournalError):
            j.undo('1')
        self.assertEqual(self.path.read_bytes(), other)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.adapter.values['a'], 2)

    def test_created_by_someone_else_after_open_refuses(self):
        j = self.journal()  # abriu sem arquivo
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': []}), encoding='utf-8')
        with self.assertRaises(cj.JournalError):
            j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        self.assertEqual(self.calls, [])

    def test_write_error_makes_instance_refuse_everything(self):
        j = self.journal()
        j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        with mock.patch.object(cj.os, 'replace', side_effect=OSError('disco cheio')):
            ok_reason = None
            with self.assertRaises(cj.JournalError):
                ok_reason = j.undo('1')
        self.assertIsNone(ok_reason)
        self.calls.clear()
        with self.assertRaises(cj.JournalError):
            j.apply_batch([{'kind': 'energia', 'key': 'b', 'after': 'alto'}])
        self.assertEqual(self.calls, [])


class FailingSave:
    """Deixa as N primeiras gravações passarem e faz a seguinte falhar."""

    def __init__(self, journal, ok_saves):
        self.real = journal._save
        self.left = ok_saves

    def __call__(self):
        if self.left <= 0:
            raise cj.JournalError('Não foi possível gravar o diário de alterações.')
        self.left -= 1
        self.real()


class SaveFailsMidBatchTest(Base):
    """(c) Gravação do diário falhando no meio do lote."""

    CHANGES = [{'kind': 'energia', 'key': 'a', 'after': 2},
               {'kind': 'energia', 'key': 'b', 'after': 'alto'},
               {'kind': 'energia', 'key': 'c', 'after': True}]

    def run_failing(self, ok_saves, j=None):
        j = j or self.journal()
        j._save = FailingSave(j, ok_saves)
        with self.assertRaises(cj.BatchRefused) as ctx:
            j.apply_batch(self.CHANGES)
        return j, str(ctx.exception)

    def test_save_fails_on_second_item_after_apply(self):
        # gravações: 1 prepared, 1 applied, 2 prepared; falha ao marcar 2 applied
        _j, message = self.run_failing(3)
        self.assertEqual(message, 'Não foi possível gravar o diário; os ajustes deste lote foram desfeitos.')
        self.assertEqual(self.adapter.values, {'a': 1, 'b': 'equilibrado', 'c': False})
        reverts = [c for c in self.calls if c[0] == 'revert']
        self.assertEqual(reverts, [('revert', 'b', 'equilibrado'), ('revert', 'a', 1)])
        self.assertNotIn(('apply', 'c', True), self.calls)

    def test_save_fails_before_second_apply(self):
        # falha ao gravar o item 2 como prepared: só o item 1 foi aplicado
        _j, message = self.run_failing(2)
        self.assertIn('foram desfeitos', message)
        self.assertEqual(self.adapter.values, {'a': 1, 'b': 'equilibrado', 'c': False})
        self.assertNotIn(('apply', 'b', 'alto'), self.calls)

    def test_revert_failing_says_check_manually(self):
        self.adapter.ignore_revert.add('a')
        _j, message = self.run_failing(3)
        self.assertEqual(message, 'Não foi possível gravar o diário; confira manualmente: '
                                  '1 ajuste(s) não voltaram ao valor anterior.')
        self.assertEqual(self.adapter.values['b'], 'equilibrado')
        self.assertEqual(self.adapter.values['a'], 2)

    def test_instance_refuses_after_failed_batch(self):
        j, _message = self.run_failing(3)
        self.calls.clear()
        with self.assertRaises(cj.JournalError):
            j.apply_batch([{'kind': 'energia', 'key': 'a', 'after': 2}])
        with self.assertRaises(cj.JournalError):
            j.undo('1')
        self.assertEqual(self.calls, [])

    def test_failed_batch_on_disk_can_be_recovered_by_new_window(self):
        self.run_failing(3)
        j = self.journal()
        self.assertEqual([e['status'] for e in j.entries()], ['applied', 'prepared'])
        self.assertEqual(j.recover_interrupted(), [('2', 'failed')])
        # o item 1 consta como aplicado, mas foi desfeito: desfazer não sobrescreve
        self.assertEqual(j.undo('1'), (False, cj.MSG_CHANGED_OUTSIDE))


class IdFormatTest(Base):
    """(d) id ou lote com dígito unicode deixa o diário ilegível, sem erro cru."""

    def write(self, **fields):
        entry = {'id': '1', 'batch': '1', 'kind': 'energia', 'key': 'a', 'before': 1,
                 'after': 2, 'status': 'applied', 'created': 'x', 'updated': 'x'}
        entry.update(fields)
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': [entry]}),
                             encoding='utf-8')

    def test_unicode_digits_are_unreadable(self):
        for field in ('id', 'batch'):
            for bad in ('²', '1²', '١', '', '01x', '1\n', ' 1', '1234567890'):
                with self.subTest(field=field, bad=bad):
                    self.write(**{field: bad})
                    with self.assertRaises(cj.JournalError) as ctx:
                        self.journal()
                    self.assertIn('ilegível', str(ctx.exception))

    def test_next_id_ignores_non_ascii(self):
        j = self.journal()
        j._entries = [{'id': '²', 'batch': '1²'}, {'id': '7', 'batch': '3'}]
        self.assertEqual(j._next_id(), '8')
        self.assertEqual(j._next_batch(), '4')


class RecoverPreparedTest(Base):
    """(e) Item interrompido que ficou no valor anterior vira "não aplicado"."""

    def test_prepared_with_before_value_becomes_failed(self):
        entry = {'id': '1', 'batch': '1', 'kind': 'energia', 'key': 'b', 'before': 'equilibrado',
                 'after': 'alto', 'status': 'prepared', 'created': 'x', 'updated': 'x'}
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': [entry]}), encoding='utf-8')
        j = self.journal()
        self.assertEqual(j.recover_interrupted(), [('1', 'failed')])
        self.assertNotIn('revert', [c[0] for c in self.calls])
        self.assertEqual([e['status'] for e in self.journal().entries()], ['failed'])


if __name__ == '__main__':
    unittest.main()
