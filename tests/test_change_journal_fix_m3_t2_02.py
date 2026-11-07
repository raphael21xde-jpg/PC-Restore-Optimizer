"""FIX-M3-T2-02: o "Desfazer tudo" pula o item cujo valor foi apagado fora do app.

Só a recusa de uma exceção do adaptador marcada com ``undo_skip_safe = True``
(o ``WindowsDefaultError`` do agendamento de GPU) deixa o lote seguir para os
itens mais antigos. O item pulado não é regravado (continua ``applied``) e
nenhum estado novo é criado. Qualquer outra recusa continua parando o lote.

Só adaptadores falsos em memória e arquivos em TemporaryDirectory. Nenhum
registro, PowerShell ou subprocess de verdade.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import advanced_tweaks as at  # noqa: E402
import change_journal as cj  # noqa: E402

KIND = 'fake'
GPU_KIND = 'fake_gpu'


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


class MarkedError(RuntimeError):
    """Exceção falsa com a marca explícita, como o ``WindowsDefaultError``."""
    undo_reason = 'Motivo marcado (simulado).'
    undo_skip_safe = True


class ReasonOnlyError(RuntimeError):
    """Tem ``undo_reason``, mas não a marca: tem que parar o lote."""
    undo_reason = 'Motivo sem marca (simulado).'


class TruthyMarkError(RuntimeError):
    """Marca "verdadeira" mas não ``True``: tem que parar (só ``is True`` vale)."""
    undo_reason = 'Motivo com marca estranha (simulado).'
    undo_skip_safe = 1


class FakeAdapter:
    """Adaptador falso em memória; ``read_error`` faz a leitura falhar."""

    def __init__(self, start):
        self.values = dict(start)
        self.read_error = {}
        self.calls = []

    def read(self, key):
        if key in self.read_error:
            raise self.read_error[key]
        return self.values[key]

    def apply(self, key, value):
        self.calls.append(('apply', key, value))
        self.values[key] = value

    def revert(self, key, value):
        self.calls.append(('revert', key, value))
        self.values[key] = value


class Base(unittest.TestCase):
    def setUp(self):
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'diario.json'
        self.fake = FakeAdapter({'a': 0, 'c': 0})
        self.gpu = FakeAdapter({'gpu': 1})
        self.journal = cj.ChangeJournal(self.path, {KIND: self.fake, GPU_KIND: self.gpu},
                                        lambda description: True)
        # A (mais antigo), GPU, C (mais novo).
        self.journal.apply_batch([{'kind': KIND, 'key': 'a', 'after': 1}])
        self.journal.apply_batch([{'kind': GPU_KIND, 'key': 'gpu', 'after': 2}])
        self.journal.apply_batch([{'kind': KIND, 'key': 'c', 'after': 1}])
        self.a_id, self.gpu_id, self.c_id = [e['id'] for e in self.journal.entries()]
        self.fake.calls.clear()
        self.gpu.calls.clear()

    def gpu_deleted_outside(self):
        del self.gpu.values['gpu']
        self.gpu.read_error['gpu'] = at.WindowsDefaultError(at.MSG_WINDOWS_DEFAULT)

    def entry(self, change_id):
        return next(e for e in self.journal.entries() if e['id'] == change_id)

    def status(self):
        return {e['id']: e['status'] for e in self.journal.entries()}


class SkipTests(Base):
    def test_marked_gpu_is_skipped_and_older_item_is_undone(self):
        """(1) done [C, A], pending [GPU]; o GPU não é regravado nem revertido."""
        self.gpu_deleted_outside()
        gpu_before = dict(self.entry(self.gpu_id))
        done, pending, reason = self.journal.undo_all()
        self.assertEqual(done, [self.c_id, self.a_id])
        self.assertEqual(pending, [self.gpu_id])
        self.assertEqual(reason, at.MSG_UNDO_WINDOWS_DEFAULT)
        self.assertEqual(self.status(), {self.a_id: 'reverted', self.gpu_id: 'applied',
                                         self.c_id: 'reverted'})
        self.assertEqual(self.entry(self.gpu_id), gpu_before)   # nem status, updated, note
        self.assertEqual(self.gpu.calls, [])                    # revert nunca chamado
        self.assertNotIn('gpu', self.gpu.values)                # não recriado
        self.assertEqual(self.fake.values, {'a': 0, 'c': 0})

    def test_second_undo_all_changes_nothing(self):
        """(2) de novo: done [], pending [GPU], mesmo motivo, diário idêntico."""
        self.gpu_deleted_outside()
        self.journal.undo_all()
        saved = self.path.read_bytes()
        self.fake.calls.clear()
        done, pending, reason = self.journal.undo_all()
        self.assertEqual((done, pending, reason), ([], [self.gpu_id], at.MSG_UNDO_WINDOWS_DEFAULT))
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(self.fake.calls + self.gpu.calls, [])

    def test_any_marked_adapter_error_is_skipped(self):
        self.gpu.read_error['gpu'] = MarkedError('x')
        done, pending, reason = self.journal.undo_all()
        self.assertEqual((done, pending, reason),
                         ([self.c_id, self.a_id], [self.gpu_id], MarkedError.undo_reason))

    def test_single_undo_is_the_same_as_before(self):
        """(7) undo(id_gpu) devolve o mesmo de antes; STATUSES não muda."""
        self.gpu_deleted_outside()
        self.assertEqual(self.journal.undo(self.gpu_id), (False, at.MSG_UNDO_WINDOWS_DEFAULT))
        self.assertEqual(self.entry(self.gpu_id)['status'], 'applied')
        self.assertEqual(cj.STATUSES, ('prepared', 'applied', 'failed', 'reverted', 'unknown'))
        self.assertTrue(at.WindowsDefaultError.undo_skip_safe)
        self.assertFalse(getattr(at.NotSupportedError, 'undo_skip_safe', False))

    def test_value_back_to_new_value_is_undone(self):
        """(8) o valor volta a 2: o "Desfazer tudo" desfaz o GPU normalmente."""
        self.gpu_deleted_outside()
        self.journal.undo_all()
        del self.gpu.read_error['gpu']
        self.gpu.values['gpu'] = 2
        done, pending, reason = self.journal.undo_all()
        self.assertEqual((done, pending, reason), ([self.gpu_id], [], ''))
        self.assertEqual(self.gpu.values['gpu'], 1)
        self.assertEqual(self.entry(self.gpu_id)['status'], 'reverted')


class StillStopsTests(Base):
    def assert_stopped_at_gpu(self, reason_wanted):
        done, pending, reason = self.journal.undo_all()
        self.assertEqual(done, [self.c_id])
        self.assertEqual(pending, [self.gpu_id, self.a_id])
        self.assertEqual(reason, reason_wanted)
        self.assertEqual(self.fake.values['a'], 1)                     # A nem tentado
        self.assertNotIn(('revert', 'a', 0), self.fake.calls)
        self.assertEqual(self.entry(self.a_id)['status'], 'applied')

    def test_reason_without_mark_stops(self):
        """(3) undo_reason sem a marca para; A nem é tentado."""
        self.gpu.read_error['gpu'] = ReasonOnlyError('x')
        self.assert_stopped_at_gpu(ReasonOnlyError.undo_reason)

    def test_mark_must_be_exactly_true(self):
        self.gpu.read_error['gpu'] = TruthyMarkError('x')
        self.assert_stopped_at_gpu(TruthyMarkError.undo_reason)

    def test_plain_read_failure_stops(self):
        """(4) leitura que falha sem motivo."""
        self.gpu.read_error['gpu'] = OSError('negado (simulado)')
        self.assert_stopped_at_gpu(cj.MSG_UNDO_NOT_READ)

    def test_changed_outside_stops(self):
        """(4) valor mudado por outro programa."""
        self.gpu.values['gpu'] = 7
        self.assert_stopped_at_gpu(cj.MSG_CHANGED_OUTSIDE)
        self.assertEqual(self.gpu.calls, [])

    def test_unknown_after_revert_stops(self):
        """(4) o desfazer não pôde ser confirmado: vira unknown e para."""
        gpu = self.gpu

        def bad_revert(key, value):
            gpu.calls.append(('revert', key, value))
            gpu.values[key] = 9
        gpu.revert = bad_revert
        done, pending, reason = self.journal.undo_all()
        self.assertEqual((done, pending), ([self.c_id], [self.gpu_id, self.a_id]))
        self.assertIn('confira manualmente', reason)
        self.assertEqual(self.entry(self.gpu_id)['status'], 'unknown')
        self.assertEqual(self.entry(self.a_id)['status'], 'applied')

    def test_older_item_with_same_key_stops(self):
        """(5) há item mais antigo applied com o mesmo (kind, key): para."""
        path = self.path.with_name('outro.json')
        gpu = FakeAdapter({'gpu': 1})
        journal = cj.ChangeJournal(path, {GPU_KIND: gpu, KIND: self.fake}, lambda d: True)
        journal.apply_batch([{'kind': GPU_KIND, 'key': 'gpu', 'after': 2}])
        journal.apply_batch([{'kind': GPU_KIND, 'key': 'gpu', 'after': 3}])
        old_id, new_id = [e['id'] for e in journal.entries()]
        del gpu.values['gpu']
        gpu.read_error['gpu'] = at.WindowsDefaultError(at.MSG_WINDOWS_DEFAULT)
        gpu.calls.clear()
        done, pending, reason = journal.undo_all()
        self.assertEqual((done, pending, reason), ([], [new_id, old_id], at.MSG_UNDO_WINDOWS_DEFAULT))
        self.assertEqual(gpu.calls, [])
        self.assertEqual({e['status'] for e in journal.entries()}, {'applied'})

    def test_refusal_after_skip_stops_with_that_reason(self):
        """(6) pula o GPU e depois A é recusado: para ali, com o motivo de A."""
        self.gpu_deleted_outside()
        self.fake.values['a'] = 5   # mudado por fora
        done, pending, reason = self.journal.undo_all()
        self.assertEqual(done, [self.c_id])
        self.assertEqual(pending, [self.gpu_id, self.a_id])
        self.assertEqual(reason, cj.MSG_CHANGED_OUTSIDE)
        self.assertEqual(self.status(), {self.a_id: 'applied', self.gpu_id: 'applied',
                                         self.c_id: 'reverted'})


if __name__ == '__main__':
    unittest.main()
