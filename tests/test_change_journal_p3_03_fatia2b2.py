"""P3-03 fatia 2b-2: botão "Conferir de novo" (``ChangeJournal.recheck``).

Tudo sintético: TemporaryDirectory, adaptador falso que conta chamadas, powercfg
falso (FakePowercfg da fatia 2a) e ponto de restauração falso. As funções reais
que rodariam powercfg/PowerShell são trocadas por funções que falham se forem
chamadas (SafetyNet da fatia 2a).
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import change_journal as cj  # noqa: E402
import optimization_engine as oe  # noqa: E402
from tests.test_change_journal_p3_03_fatia2 import (  # noqa: E402
    A, B, C, NO_DISPLAY, SafetyNet)
from tests import test_change_journal_p3_03_fatia2b as f2b  # noqa: E402
from tests.test_change_journal_p3_03_fatia2b import _entry  # noqa: E402

try:
    import optimization_ui as ou
except ImportError:  # Python sem Tk: os testes de tela pulam.
    ou = None

KIND = 'fake'
T0 = '2026-10-30T00:00:00+00:00'


class CountingAdapter:
    """Adaptador falso: valores em memória e contagem de cada chamada."""
    label = 'Ajuste de teste'

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.calls = {'read': 0, 'apply': 0, 'revert': 0}
        self.read_error = set()
        self.fail_apply = set()

    def read(self, key):
        self.calls['read'] += 1
        if key in self.read_error:
            raise OSError('C:\\Users\\Fulano\\erro cru')
        return self.values.get(key)

    def apply(self, key, value):
        self.calls['apply'] += 1
        if key in self.fail_apply:
            raise OSError('falhou')
        self.values[key] = value

    def revert(self, key, value):
        self.calls['revert'] += 1
        self.values[key] = value


def _raw(number, status, before, after, key=None, note=None):
    entry = {'id': str(number), 'batch': str(number), 'kind': KIND, 'key': key or f'k{number}',
             'before': before, 'after': after, 'status': status, 'created': T0, 'updated': T0}
    if note is not None:
        entry['note'] = note
    return entry


class RecheckEngineTests(SafetyNet):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / 'diario.json'
        self.adapter = CountingAdapter()
        self.restore_calls = []

    def restore_point(self, description):
        self.restore_calls.append(description)
        return True

    def write(self, *entries):
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': list(entries)}),
                             encoding='utf-8')

    def open(self, adapters=None):
        return cj.ChangeJournal(self.path, adapters or {KIND: self.adapter}, self.restore_point)

    def statuses(self, journal):
        return {e['id']: e['status'] for e in journal.entries()}

    def disk_statuses(self):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        return {e['id']: e['status'] for e in data['entries']}

    # ---------- tabela de transições ----------
    def test_transition_table(self):
        cases = (
            # (estado, valor atual, nota, estado esperado, lista do resultado)
            ('applied', 'A', None, 'reverted', 'changed'),
            ('applied', 'N', None, 'applied', None),
            ('applied', 'X', None, 'applied', 'outside'),
            ('unknown', 'N', None, 'applied', 'changed'),
            ('unknown', 'A', cj.NOTE_UNDO, 'reverted', 'changed'),
            ('unknown', 'A', None, 'failed', 'changed'),
            ('unknown', 'A', 'outra nota', 'failed', 'changed'),
            ('unknown', 'X', cj.NOTE_UNDO, 'unknown', None),
            ('unknown', 'X', None, 'unknown', None),
        )
        for status, current, note, expected, bucket in cases:
            with self.subTest(status=status, current=current, note=note):
                self.adapter = CountingAdapter({'k1': current})
                self.write(_raw(1, status, 'A', 'N', note=note))
                journal = self.open()
                result = journal.recheck()
                self.assertEqual(self.statuses(journal), {'1': expected})
                self.assertEqual(self.disk_statuses(), {'1': expected})
                self.assertEqual(result['changed'],
                                 [('1', status, expected)] if bucket == 'changed' else [])
                self.assertEqual(result['outside'], ['1'] if bucket == 'outside' else [])
                self.assertEqual(result['unreadable'], [])
                self.assertEqual(self.adapter.calls, {'read': 1, 'apply': 0, 'revert': 0})

    def test_unreadable_changes_nothing(self):
        self.adapter = CountingAdapter({'k1': 'A', 'k2': 'N'})
        self.adapter.read_error = {'k1', 'k2'}
        self.write(_raw(1, 'applied', 'A', 'N'), _raw(2, 'unknown', 'A', 'N'))
        before = self.path.read_bytes()
        journal = self.open()
        result = journal.recheck()
        self.assertEqual(result, {'changed': [], 'outside': [], 'unreadable': ['1', '2']})
        self.assertEqual(self.statuses(journal), {'1': 'applied', '2': 'unknown'})
        self.assertEqual(self.path.read_bytes(), before)  # nada a gravar
        self.assertEqual(self.adapter.calls, {'read': 2, 'apply': 0, 'revert': 0})

    def test_ignored_entries_are_not_even_read(self):
        self.adapter = CountingAdapter({f'k{n}': 'A' for n in range(1, 7)})
        self.write(_raw(1, 'prepared', 'A', 'N'), _raw(2, 'failed', 'A', 'N'),
                   _raw(3, 'reverted', 'A', 'N'), _raw(4, 'applied', 'A', 'A'),
                   _raw(5, 'unknown', 'A', 'A'),
                   dict(_raw(6, 'applied', 'A', 'N'), kind='outro'))
        before = self.path.read_bytes()
        journal = self.open()
        result = journal.recheck()
        self.assertEqual(result, {'changed': [], 'outside': [], 'unreadable': []})
        self.assertEqual(self.statuses(journal),
                         {'1': 'prepared', '2': 'failed', '3': 'reverted', '4': 'applied',
                          '5': 'unknown', '6': 'applied'})
        self.assertEqual(self.adapter.calls, {'read': 0, 'apply': 0, 'revert': 0})
        self.assertEqual(self.path.read_bytes(), before)

    def test_never_applies_reverts_or_creates_restore_point(self):
        self.adapter = CountingAdapter({'k1': 'A', 'k2': 'N', 'k3': 'X', 'k4': 'N'})
        self.write(_raw(1, 'applied', 'A', 'N'), _raw(2, 'applied', 'A', 'N'),
                   _raw(3, 'applied', 'A', 'N'), _raw(4, 'unknown', 'A', 'N'))
        journal = self.open()
        with mock.patch.object(journal, 'apply_batch', side_effect=AssertionError), \
                mock.patch.object(journal, 'undo', side_effect=AssertionError), \
                mock.patch.object(journal, 'undo_all', side_effect=AssertionError):
            journal.recheck()
        self.assertEqual(self.adapter.calls, {'read': 4, 'apply': 0, 'revert': 0})
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.adapter.values, {'k1': 'A', 'k2': 'N', 'k3': 'X', 'k4': 'N'})

    def test_all_changes_in_one_write(self):
        self.adapter = CountingAdapter({'k1': 'A', 'k2': 'N'})
        self.write(_raw(1, 'applied', 'A', 'N'), _raw(2, 'unknown', 'A', 'N'))
        journal = self.open()
        with mock.patch.object(journal, '_save', wraps=journal._save) as save:
            journal.recheck()
        self.assertEqual(save.call_count, 1)
        self.assertEqual(self.disk_statuses(), {'1': 'reverted', '2': 'applied'})

    # ---------- unknown vindo de "desfazer" ----------
    def test_undo_unknown_gets_note_and_recheck_reverts(self):
        self.adapter = CountingAdapter({'k1': 'A'})
        journal = self.open()
        journal.apply_batch([{'kind': KIND, 'key': 'k1', 'after': 'N'}])
        # O desfazer não é confirmado: o valor fica estranho logo depois.
        original_revert = self.adapter.revert

        def odd_revert(key, value):
            original_revert(key, value)
            self.adapter.values[key] = 'X'
        self.adapter.revert = odd_revert
        ok, _reason = journal.undo('1')
        self.assertFalse(ok)
        entry = journal.entries()[0]
        self.assertEqual((entry['status'], entry['note']), ('unknown', cj.NOTE_UNDO))
        # Depois o valor volta ao anterior (por exemplo, o Windows terminou a troca).
        self.adapter.values['k1'] = 'A'
        reads = self.adapter.calls['read']
        result = journal.recheck()
        self.assertEqual(result['changed'], [('1', 'unknown', 'reverted')])
        self.assertEqual(self.disk_statuses(), {'1': 'reverted'})
        self.assertEqual(self.adapter.calls['read'] - reads, 1)
        self.assertFalse(journal.has_blocking())

    # ---------- ressalva 3 da PR #124 ----------
    def test_review_note_3_batch_save_failure_then_recheck(self):
        self.adapter = CountingAdapter({'k1': 'A', 'k2': 'A'})
        journal = self.open()
        original = journal._save
        state = {'calls': 0}

        def save():
            state['calls'] += 1
            if state['calls'] == 3:  # 1: k1 prepared, 2: k1 applied, 3: k2 prepared
                raise cj.JournalError('Não foi possível gravar o diário de alterações.')
            return original()
        with mock.patch.object(journal, '_save', side_effect=save):
            with self.assertRaises(cj.BatchRefused) as caught:
                journal.apply_batch([{'kind': KIND, 'key': 'k1', 'after': 'N'},
                                     {'kind': KIND, 'key': 'k2', 'after': 'N'}])
        self.assertEqual(str(caught.exception), cj.MSG_BATCH_SAVE_FAILED)
        self.assertEqual(self.adapter.values, {'k1': 'A', 'k2': 'A'})
        self.assertEqual(self.disk_statuses(), {'1': 'applied'})  # o diário ficou atrasado
        reopened = self.open()
        calls = dict(self.adapter.calls)
        result = reopened.recheck()
        self.assertEqual(result, {'changed': [('1', 'applied', 'reverted')],
                                  'outside': [], 'unreadable': []})
        self.assertEqual(self.disk_statuses(), {'1': 'reverted'})
        self.assertEqual(self.adapter.calls['apply'], calls['apply'])
        self.assertEqual(self.adapter.calls['revert'], calls['revert'])

    # ---------- diário mudado e falha de gravação ----------
    def test_journal_changed_by_other_window_reads_nothing(self):
        self.adapter = CountingAdapter({'k1': 'A'})
        self.write(_raw(1, 'applied', 'A', 'N'))
        journal = self.open()
        other = b'{"outra": "janela"}'
        self.path.write_bytes(other)
        with self.assertRaises(cj.JournalError) as caught:
            journal.recheck()
        self.assertEqual(str(caught.exception), cj.MSG_OTHER_WINDOW)
        self.assertEqual(self.adapter.calls['read'], 0)
        self.assertEqual(self.path.read_bytes(), other)

    def test_save_failure_keeps_file_and_memory(self):
        self.adapter = CountingAdapter({'k1': 'A', 'k2': 'N'})
        self.write(_raw(1, 'applied', 'A', 'N'), _raw(2, 'unknown', 'A', 'N', note=cj.NOTE_UNDO))
        raw = self.path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        journal = self.open()
        before = journal.entries()
        with mock.patch.object(cj.os, 'replace', side_effect=OSError('disco cheio')):
            with self.assertRaises(cj.JournalError) as caught:
                journal.recheck()
        self.assertNotIn('disco cheio', str(caught.exception))
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), digest)
        self.assertEqual(journal.entries(), before)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ['diario.json'])
        # Depois de uma falha ao gravar, a instância recusa tudo até reabrir.
        with self.assertRaises(cj.JournalError) as again:
            journal.recheck()
        self.assertIn('Nada foi gravado', str(again.exception))


    def test_interrupt_mid_loop_restores_memory(self):
        # FIX-P3-03-09: exceção fora de Exception (ex.: KeyboardInterrupt) no meio do
        # laço não pode deixar a 1ª entrada mudada só na memória.
        self.adapter = CountingAdapter({'k1': 'A', 'k2': 'N'})
        self.write(_raw(1, 'applied', 'A', 'N'), _raw(2, 'applied', 'A', 'N'))
        raw = self.path.read_bytes()
        journal = self.open()
        before = journal.entries()
        original = journal._read

        def read(entry):
            if entry['id'] == '2':
                raise KeyboardInterrupt
            return original(entry)
        with mock.patch.object(journal, '_read', side_effect=read):
            with self.assertRaises(KeyboardInterrupt):
                journal.recheck()
        self.assertEqual(journal.entries(), before)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(self.adapter.calls, {'read': 1, 'apply': 0, 'revert': 0})
        self.assertEqual(self.restore_calls, [])


class RecheckTabHelpers(f2b.ChangesTabHelpers):
    def recheck(self, panel):
        panel.btn_recheck.invoke()
        self.wait_idle(panel)


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class RecheckTabTests(RecheckTabHelpers):
    def test_button_disabled_with_broken_journal(self):
        self.journal_file.write_bytes(b'\x00 quebrado')
        panel = self.panel()
        self.root.update()
        self.assertTrue(panel.btn_recheck.instate(['disabled']))
        job = panel._power_job
        panel.recheck_changes()
        self.root.update()
        self.assertIs(panel._power_job, job)
        self.assertEqual(self.fake.calls, [])

    def test_button_disabled_without_applied_or_unknown(self):
        self.write_journal(_entry(1, 'reverted', A, B), _entry(2, 'failed', A, C))
        panel = self.panel()
        self.root.update()
        self.assertTrue(panel.btn_recheck.instate(['disabled']))
        job = panel._power_job
        panel.recheck_changes()
        self.root.update()
        self.assertIs(panel._power_job, job)
        self.assertEqual(panel.changes_status.get(), ou.CHANGES_RECHECK_NOTHING_TEXT)
        self.assertEqual(self.fake.calls, [])

    def test_unknown_resolved_releases_apply(self):
        self.write_journal(_entry(1, 'unknown', A, B))
        self.fake.current = B
        panel = self.panel()
        self.root.update()
        self.assertTrue(panel.btn_apply.instate(['disabled']))
        self.assertTrue(panel.btn_recheck.instate(['!disabled']))
        self.assertIn(ou.CHANGES_UNKNOWN_TEXT.format(n=1), self.changes(panel))
        self.recheck(panel)
        self.assertEqual(panel.changes_status.get(), ou.CHANGES_RECHECK_FIXED_TEXT.format(n=1))
        self.assertEqual([e['status'] for e in self.entries()], ['applied'])
        self.assertNotIn(ou.CHANGES_UNKNOWN_TEXT.format(n=1), self.changes(panel))
        self.assertEqual(panel.power_block.get(), '')
        self.assertTrue(panel.btn_apply.instate(['!disabled']))
        # Só leitura: sem confirmação, sem ponto de restauração, sem troca de plano.
        self.assertEqual(self.answers, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.fake.setactive(), [])
        self.assertEqual(self.messages, [])

    def test_nothing_to_fix_and_outside_texts(self):
        self.write_journal(_entry(1, 'applied', A, B))
        self.fake.current = B
        panel = self.panel()
        self.recheck(panel)
        self.assertEqual(panel.changes_status.get(), ou.CHANGES_RECHECK_SAME_TEXT)
        self.fake.current = C  # outro programa trocou o plano
        self.recheck(panel)
        # FIX-P3-03-09 (R-33): com item mudado por fora, a frase é neutra + aviso.
        expected = (ou.CHANGES_RECHECK_NONE_CHANGED_TEXT
                    + ou.CHANGES_RECHECK_OUTSIDE_TEXT.format(n=1))
        self.assertEqual(panel.changes_status.get(), expected)
        self.assertNotIn('já estava certo', panel.changes_status.get())
        self.assertEqual(self.messages, [('warning', ou.CHANGES_RECHECK_TITLE, expected)])
        self.assertEqual([e['status'] for e in self.entries()], ['applied'])
        self.assertEqual(self.fake.setactive(), [])

    def test_unreadable_item_text_and_one_warning(self):
        # FIX-P3-03-09 (R-33): item ilegível não pode virar "o diário já estava certo".
        self.write_journal(_entry(1, 'applied', A, B))
        self.fake.current = B
        panel = self.panel()
        self.fake.active_error = OSError('C:\\Users\\Fulano\\erro cru')
        self.recheck(panel)
        expected = (ou.CHANGES_RECHECK_NONE_CHANGED_TEXT
                    + ou.CHANGES_RECHECK_UNREADABLE_TEXT.format(n=1))
        self.assertEqual(panel.changes_status.get(), expected)
        self.assertNotIn('já estava certo', panel.changes_status.get())
        self.assertEqual(self.messages, [('warning', ou.CHANGES_RECHECK_TITLE, expected)])
        self.assertEqual([e['status'] for e in self.entries()], ['applied'])
        self.assertEqual(self.fake.setactive(), [])

    def test_unexpected_error_disables_buttons(self):
        self.write_journal(_entry(1, 'applied', A, B))
        self.fake.current = B
        panel = self.panel()
        with mock.patch.object(panel.journal, 'recheck',
                               side_effect=RuntimeError('C:\\Users\\Fulano\\erro cru')):
            self.recheck(panel)
        expected = ou.CHANGES_RECHECK_ERROR_TEXT
        self.assertEqual(self.messages, [('error', ou.CHANGES_RECHECK_TITLE, expected)])
        self.assertEqual(panel.changes_status.get(), expected)
        self.assertNotIn('Fulano', ' '.join(m[2] for m in self.messages))
        for button in (panel.btn_apply, panel.btn_revert, panel.btn_undo_all, panel.btn_recheck):
            self.assertTrue(button.instate(['disabled']))
        self.assertEqual(self.fake.setactive(), [])

    def test_journal_error_goes_to_journal_failed(self):
        self.write_journal(_entry(1, 'applied', A, B))
        self.fake.current = A
        panel = self.panel()
        self.journal_file.write_bytes(b'{"outra": "janela"}')
        self.recheck(panel)
        self.assertEqual(self.messages[-1][0], 'error')
        self.assertIn(cj.MSG_OTHER_WINDOW, self.messages[-1][2])
        for button in (panel.btn_apply, panel.btn_revert, panel.btn_undo_all, panel.btn_recheck):
            self.assertTrue(button.instate(['disabled']))
        self.assertEqual(self.journal_file.read_bytes(), b'{"outra": "janela"}')

    def test_runs_in_job_and_busy_click_starts_nothing(self):
        self.write_journal(_entry(1, 'applied', A, B))
        self.fake.current = B
        gate = threading.Event()
        self.addCleanup(gate.set)
        threads = []
        original = self.fake.active

        def active():
            threads.append(threading.current_thread())
            gate.wait(5)
            return original()
        self.fake.active = active  # antes do painel: o adaptador guarda a função
        panel = self.panel()
        started = time.monotonic()
        panel.btn_recheck.invoke()
        self.assertLess(time.monotonic() - started, 1.0)
        self.root.update()
        self.assertTrue(panel.power_busy)
        for button in (panel.btn_recheck, panel.btn_undo_all, panel.btn_apply, panel.btn_refresh):
            self.assertTrue(button.instate(['disabled']))
        job = panel._power_job
        panel.recheck_changes()
        panel.undo_all_changes()
        self.assertIs(panel._power_job, job)
        gate.set()
        self.wait_idle(panel)
        self.assertTrue(threads)
        for thread in threads:
            self.assertIsNot(thread, threading.main_thread())
        # FIX-P3-03-09: o Job também tem de chegar ao resultado certo.
        self.assertEqual(panel.changes_status.get(), ou.CHANGES_RECHECK_SAME_TEXT)
        self.assertEqual(self.messages, [])
        self.assertEqual(self.fake.setactive(), [])


if __name__ == '__main__':
    unittest.main()
