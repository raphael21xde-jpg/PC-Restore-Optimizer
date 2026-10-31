"""P3-03 fatia 2b-1: subaba "Alterações feitas" e "Desfazer tudo".

Tudo sintético: TemporaryDirectory, powercfg falso (FakePowercfg da fatia 2a),
ponto de restauração falso e teste de administrador falso. As funções reais
que rodariam powercfg/PowerShell são trocadas por funções que falham se forem
chamadas (SafetyNet da fatia 2a).
"""
from __future__ import annotations

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
from tests import test_change_journal_p3_03_fatia2 as f2  # noqa: E402
from tests.test_change_journal_p3_03_fatia2 import (  # noqa: E402
    A, B, C, NO_DISPLAY, FakePowercfg, SafetyNet, _forbidden)
from tk_helpers import track_tk_root  # noqa: E402

try:
    import tkinter as tk
    import optimization_ui as ou
except ImportError:  # Python sem Tk: os testes de tela pulam.
    tk = ou = None

NADA = 'Nada foi gravado'


def _entry(number, status, before, after):
    return {'id': str(number), 'batch': str(number), 'kind': oe.POWER_KIND, 'key': oe.POWER_KEY,
            'before': before, 'after': after, 'status': status,
            'created': '2026-10-30T00:00:00+00:00', 'updated': '2026-10-30T00:00:00+00:00'}


def _swap_after_first_undo(journal, path, payload):
    """Troca o arquivo do diário (como outra janela) logo depois do 1º desfazer."""
    original = journal.undo
    state = {'calls': 0}

    def undo(change_id):
        result = original(change_id)
        state['calls'] += 1
        if state['calls'] == 1:
            Path(path).write_bytes(payload)
        return result
    return mock.patch.object(journal, 'undo', side_effect=undo)


class UndoAllEngineTests(SafetyNet):
    """O motor: retorno de undo_all inalterado e ``exc.done`` no JournalError."""

    def journal(self, fake):
        adapter = oe.PowerPlanAdapter(run=fake.run, active=fake.active, plans=fake.plans)
        return cj.ChangeJournal(self.tmp / 'diario.json', {oe.POWER_KIND: adapter},
                                lambda description: True)

    def two_changes(self):
        fake = FakePowercfg()
        journal = self.journal(fake)
        journal.apply_batch([{'kind': oe.POWER_KIND, 'key': oe.POWER_KEY, 'after': B}])
        journal.apply_batch([{'kind': oe.POWER_KIND, 'key': oe.POWER_KEY, 'after': C}])
        return fake, journal

    def test_undo_all_return_unchanged(self):
        fake, journal = self.two_changes()
        self.assertEqual(journal.undo_all(), (['2', '1'], [], ''))
        self.assertEqual(fake.current, A)
        self.assertEqual(journal.undo_all(), ([], [], ''))

    def test_undo_all_return_unchanged_when_stopping(self):
        fake, journal = self.two_changes()
        fake.current = A  # outro programa mexeu
        self.assertEqual(journal.undo_all(), ([], ['2', '1'], cj.MSG_CHANGED_OUTSIDE))
        self.assertEqual([e['status'] for e in journal.entries()], ['applied', 'applied'])

    def test_journal_error_midway_carries_done(self):
        fake, journal = self.two_changes()
        path = self.tmp / 'diario.json'
        swapped = b'{"outra": "janela"}'
        with _swap_after_first_undo(journal, path, swapped):
            with self.assertRaises(cj.JournalError) as caught:
                journal.undo_all()
        self.assertEqual(caught.exception.done, ['2'])
        self.assertEqual(str(caught.exception), cj.MSG_OTHER_WINDOW)
        self.assertEqual(fake.current, B)  # só o mais novo foi desfeito
        self.assertEqual(path.read_bytes(), swapped)  # nunca sobrescreve

    def test_journal_error_before_loop_has_no_done(self):
        _fake, journal = self.two_changes()
        (self.tmp / 'diario.json').write_bytes(b'{}')
        with self.assertRaises(cj.JournalError) as caught:
            journal.undo_all()
        self.assertEqual(getattr(caught.exception, 'done', []), [])


class ChangesTabHelpers(SafetyNet):
    """Só ajudantes (nenhum ``test_``): base das classes de teste da aba 7.

    FIX-P3-03-04: as classes de teste herdam daqui, e não umas das outras, para não
    rodar testes herdados duas vezes.
    """
    # Ajudantes reaproveitados da fatia 2a (sem herdar os testes dela).
    journal_file = f2.PowerPanelTests.journal_file
    legacy_file = f2.PowerPanelTests.legacy_file
    entries = f2.PowerPanelTests.entries
    wait_idle = f2.PowerPanelTests.wait_idle
    choose = f2.PowerPanelTests.choose
    apply = f2.PowerPanelTests.apply

    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)
        self.fake = FakePowercfg()
        self.admin = {'value': True}
        self.restore_calls = []
        self.messages = []
        self.answers = []
        self.answer = {'value': True}

    def restore_point(self, description):
        self.restore_calls.append(description)
        return True

    def panel(self):
        adapter = oe.PowerPlanAdapter(run=self.fake.run, active=self.fake.active,
                                      plans=self.fake.plans)

        def ask(title, text):
            self.answers.append((title, text))
            return self.answer['value']

        panel = ou.OptimizationPanel(
            self.root, app_dir=self.tmp, state_dir=self.tmp, power_adapter=adapter,
            restore_point=self.restore_point, elevated_probe=lambda: self.admin['value'],
            ask=ask, show=lambda kind, title, text: self.messages.append((kind, title, text)))
        panel.pack()
        return panel

    def write_journal(self, *entries):
        self.journal_file.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': list(entries)}),
                                     encoding='utf-8')

    def changes(self, panel):
        return panel.changes_text.get('1.0', 'end')

    def two_changes(self):
        panel = self.panel()
        self.apply(panel, B)
        self.apply(panel, C)
        self.assertEqual(self.fake.current, C)
        self.assertEqual(len(self.restore_calls), 2)
        return panel

    def undo_all(self, panel):
        panel.btn_undo_all.invoke()
        self.wait_idle(panel)


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class ChangesTabTests(ChangesTabHelpers):
    # ---------- abrir a aba ----------
    def test_tab_lists_summary_without_commands(self):
        self.write_journal(_entry(1, 'reverted', A, B), _entry(2, 'applied', A, C))
        panel = self.panel()
        self.root.update()
        names = [panel.tabs.tab(t, 'text') for t in panel.tabs.tabs()]
        self.assertIn('7  Alterações feitas', names)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.restore_calls, [])
        text = self.changes(panel)
        for line in panel.journal.summary_lines():
            self.assertIn(line, text)
        self.assertIn('1. Plano de energia: desfeita.', text)
        self.assertIn('2. Plano de energia: aplicada.', text)
        self.assertTrue(panel.btn_undo_all.instate(['!disabled']))

    def test_tab_with_unreadable_journal_disables_undo_all(self):
        raw = b'{isto nao e um diario'
        self.journal_file.write_bytes(raw)
        panel = self.panel()
        self.root.update()
        text = self.changes(panel)
        self.assertIn(panel.journal_error, text)
        self.assertIn(ou.POWER_JOURNAL_OFF_TEXT, text)
        self.assertTrue(panel.btn_undo_all.instate(['disabled']))
        panel.undo_all_changes()
        self.wait_idle(panel)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.answers, [])
        self.assertEqual(self.journal_file.read_bytes(), raw)
        self.assertNotIn(str(self.tmp), text)

    # ---------- sem nada aplicado ----------
    def test_undo_all_disabled_when_nothing_applied(self):
        panel = self.panel()
        self.root.update()
        self.assertTrue(panel.btn_undo_all.instate(['disabled']))
        self.assertIn('Nenhuma alteração registrada.', self.changes(panel))
        self.write_journal(_entry(1, 'reverted', A, B))
        panel2 = self.panel()
        self.root.update()
        self.assertTrue(panel2.btn_undo_all.instate(['disabled']))

    def test_undo_all_disabled_when_nothing_applied_clicking_runs_nothing(self):
        self.write_journal(_entry(1, 'reverted', A, B))
        raw = self.journal_file.read_bytes()
        panel = self.panel()
        self.root.update()
        job_antes = panel._power_job
        panel.btn_undo_all.invoke()
        panel.undo_all_changes()  # mesmo chamando direto
        self.root.update()
        self.assertIs(panel._power_job, job_antes)
        self.assertEqual(self.answers, [])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.journal_file.read_bytes(), raw)
        self.assertEqual(panel.changes_status.get(), ou.CHANGES_EMPTY_TEXT)
        self.assertEqual(self.messages[-1], ('info', 'Desfazer tudo', ou.CHANGES_EMPTY_TEXT))

    # ---------- confirmação ----------
    def test_undo_all_asks_and_cancel_changes_nothing(self):
        panel = self.two_changes()
        raw = self.journal_file.read_bytes()
        calls = len(self.fake.calls)
        job_antes = panel._power_job
        self.answer['value'] = False
        panel.btn_undo_all.invoke()
        self.root.update()
        title, text = self.answers[-1]
        self.assertEqual(title, 'Desfazer tudo')
        self.assertIn('2 alteração(ões)', text)
        self.assertIn('da mais nova para a mais antiga', text)
        self.assertIn('não cria ponto de restauração', text)
        self.assertIn('o app para ali', text)
        self.assertIs(panel._power_job, job_antes)
        self.assertEqual(len(self.fake.calls), calls)
        self.assertEqual(self.fake.current, C)
        self.assertEqual(self.journal_file.read_bytes(), raw)

    # ---------- desfazer tudo ----------
    def test_undo_all_reverts_in_reverse_order_without_restore_point(self):
        panel = self.two_changes()
        self.admin['value'] = False  # não exige administrador
        self.undo_all(panel)
        self.assertEqual(self.fake.current, A)
        self.assertEqual(self.fake.setactive()[-2:], [('powercfg', '/setactive', B),
                                                      ('powercfg', '/setactive', A)])
        self.assertEqual([e['status'] for e in self.entries()], ['reverted', 'reverted'])
        self.assertEqual(len(self.restore_calls), 2)  # não cresceu
        self.assertEqual(panel.changes_status.get(), 'Todas as 2 alterações foram desfeitas.')
        self.assertIn('1. Plano de energia: desfeita.', self.changes(panel))
        self.assertTrue(panel.btn_undo_all.instate(['disabled']))
        self.assertTrue(panel.btn_apply.instate(['!disabled']))
        # A lista de planos foi atualizada depois da tarefa.
        self.assertIn('● Equilibrado', panel.power_text.get('1.0', 'end'))

    def test_undo_all_stops_on_outside_change(self):
        panel = self.two_changes()
        original = panel.journal.undo
        state = {'calls': 0}

        def undo(change_id):
            result = original(change_id)
            state['calls'] += 1
            if state['calls'] == 1:
                self.fake.current = C  # outro programa trocou de novo
            return result
        with mock.patch.object(panel.journal, 'undo', side_effect=undo):
            self.undo_all(panel)
        self.assertEqual(self.fake.current, C)
        self.assertEqual([e['status'] for e in self.entries()], ['applied', 'reverted'])
        expected = '1 desfeita(s); 1 continuam como estavam. Motivo: ' + cj.MSG_CHANGED_OUTSIDE
        self.assertEqual(panel.changes_status.get(), expected)
        self.assertEqual(self.messages[-1], ('warning', 'Desfazer tudo', expected))
        self.assertTrue(panel.btn_undo_all.instate(['!disabled']))  # ainda há 1 aplicada

    def test_undo_all_journal_error_midway_never_says_nada_foi_gravado(self):
        panel = self.two_changes()
        swapped = b'{"outra": "janela"}'
        with _swap_after_first_undo(panel.journal, self.journal_file, swapped):
            self.undo_all(panel)
        self.assertEqual(self.fake.current, B)
        self.assertEqual(self.journal_file.read_bytes(), swapped)
        kind, title, text = self.messages[-1]
        self.assertEqual((kind, title), ('error', 'Diário de alterações'))
        self.assertTrue(text.startswith('1 alteração(ões) já foram desfeitas antes do erro. '))
        self.assertIn('outra janela', text)
        for shown in (text, panel.journal_error, panel.changes_status.get(),
                      panel.power_status.get(), self.changes(panel)):
            self.assertNotIn(NADA, shown)
        self.assertTrue(panel.btn_undo_all.instate(['disabled']))
        self.assertTrue(panel.btn_apply.instate(['disabled']))
        self.assertTrue(panel.btn_revert.instate(['disabled']))

    def test_undo_all_journal_error_before_anything_keeps_message(self):
        panel = self.two_changes()
        self.journal_file.write_bytes(b'{"outra": "janela"}')
        self.undo_all(panel)
        self.assertEqual(self.fake.current, C)
        self.assertEqual(self.messages[-1][2], cj.MSG_OTHER_WINDOW + ' ' + ou.POWER_JOURNAL_OFF_TEXT)

    def test_undo_all_unexpected_error_shows_generic_text(self):
        panel = self.two_changes()
        with mock.patch.object(panel.journal, 'undo_all',
                               side_effect=RuntimeError('C:\\Users\\Fulano\\erro cru')):
            self.undo_all(panel)
        # FIX-P3-03-03 (R-27): o texto diz que parte pode já ter mudado e desliga o diário.
        expected = ou.CHANGES_UNEXPECTED_ERROR_TEXT
        # FIX-P3-03-04 (R-28): uma janela só, com o título "Desfazer tudo".
        self.assertEqual(self.messages,
                         [('error', 'Desfazer tudo', expected + ' ' + ou.POWER_JOURNAL_OFF_TEXT)])
        self.assertEqual(panel.changes_status.get(), expected)
        self.assertNotIn('Fulano', ' '.join(m[2] for m in self.messages))

    # ---------- estado desconhecido ----------
    def test_unknown_entry_shows_guidance_and_apply_refused_before_ask(self):
        self.write_journal(_entry(1, 'applied', A, B), _entry(2, 'unknown', B, C))
        self.fake.current = B
        panel = self.panel()
        self.root.update()
        self.assertEqual(self.fake.calls, [])
        expected = ou.CHANGES_UNKNOWN_TEXT.format(n=1)
        self.assertTrue(expected.startswith('1 ajuste(s) com estado desconhecido.'))
        self.assertIn(expected, self.changes(panel))
        self.assertIn('estado desconhecido (confira manualmente)', self.changes(panel))
        self.assertTrue(panel.btn_apply.instate(['disabled']))
        self.choose(panel, C)
        job_antes = panel._power_job
        panel.apply_plan()  # mesmo chamando direto
        self.root.update()
        self.assertEqual(self.answers, [])
        self.assertIs(panel._power_job, job_antes)
        self.assertEqual(self.messages[-1], ('warning', 'Plano de energia', expected))
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.fake.setactive(), [])
        # "Desfazer tudo" continua permitido para o item aplicado.
        self.assertTrue(panel.btn_undo_all.instate(['!disabled']))
        self.undo_all(panel)
        self.assertEqual(self.fake.current, A)
        self.assertEqual([e['status'] for e in self.entries()], ['reverted', 'unknown'])
        self.assertIn(expected, self.changes(panel))
        self.assertTrue(panel.btn_apply.instate(['disabled']))

    # ---------- registro antigo ----------
    def test_legacy_pending_and_unreadable_show_guidance_no_release_button(self):
        pending = json.dumps({'schema': 'pcro-power-1', 'status': 'prepared',
                              'previous': A, 'requested': B}).encode('utf-8')
        cases = ((pending, ou.POWER_LEGACY_PENDING_TEXT),
                 (b'\x00 registro quebrado', ou.POWER_LEGACY_UNREADABLE_TEXT))
        for raw, guidance in cases:
            with self.subTest(guidance=guidance[:30]):
                self.legacy_file().write_bytes(raw)
                self.messages.clear()
                with mock.patch.object(ou, 'revert_power_plan', side_effect=_forbidden):
                    panel = self.panel()
                    self.root.update()
                    text = self.changes(panel)
                    self.assertIn(guidance, text)
                    self.assertIn(ou.CHANGES_LEGACY_BLOCKED_TEXT, text)
                    self.assertIn('o bloqueio continua', ou.CHANGES_LEGACY_BLOCKED_TEXT)
                    buttons = []
                    stack = [panel.changes_frame]
                    while stack:
                        widget = stack.pop()
                        stack.extend(widget.winfo_children())
                        if widget.winfo_class() in ('TButton', 'Button'):
                            buttons.append(widget)
                    self.assertEqual(buttons, [panel.btn_undo_all])
                    self.assertTrue(panel.btn_undo_all.instate(['disabled']))
                    panel.undo_all_changes()
                    self.root.update()
                self.assertEqual(self.fake.calls, [])
                self.assertEqual(self.answers, [])
                self.assertEqual(self.legacy_file().read_bytes(), raw)
                self.assertTrue(panel.btn_apply.instate(['disabled']))
                self.assertFalse(self.journal_file.exists())
                panel.destroy()

    # ---------- thread e janela ----------
    def test_undo_all_runs_in_job_and_busy_disables_buttons(self):
        gate = threading.Event()
        gate.set()
        self.addCleanup(gate.set)
        threads = []
        original = self.fake.run

        def run(command, timeout=18):
            threads.append(threading.current_thread())
            gate.wait(5)
            return original(command, timeout)
        self.fake.run = run  # antes do painel: o adaptador guarda a função
        panel = self.two_changes()
        threads.clear()
        gate.clear()
        started = time.monotonic()
        panel.btn_undo_all.invoke()
        self.assertLess(time.monotonic() - started, 1.0)
        self.root.update()
        self.assertTrue(panel.power_busy)
        for button in (panel.btn_undo_all, panel.btn_apply, panel.btn_revert, panel.btn_refresh):
            self.assertTrue(button.instate(['disabled']))
        job = panel._power_job
        # Ocupado: um segundo clique não inicia outra tarefa.
        panel.undo_all_changes()
        self.assertIs(panel._power_job, job)
        panel.destroy()  # fechar a janela no meio
        gate.set()
        job.thread.join(5)
        self.assertFalse(job.thread.is_alive())
        for _ in range(10):  # nenhum TclError no laço de eventos
            self.root.update()
            time.sleep(0.02)
        self.assertTrue(threads)
        for thread in threads:
            self.assertIsNot(thread, threading.main_thread())
        self.assertEqual(self.fake.current, A)
        self.assertEqual(len(self.restore_calls), 2)


if __name__ == '__main__':
    unittest.main()
