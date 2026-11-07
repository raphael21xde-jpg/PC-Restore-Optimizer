"""P3-05 fatia 1: aba "9  Ajustes avançados" com Tk de verdade.

Registro falso em memória, ponto de restauração falso e subprocess bloqueado.
Nenhum registro, PowerShell ou powercfg de verdade. Arquivos só em
TemporaryDirectory. Sem Tk (ou sem tela) os testes de janela pulam; os de
código-fonte rodam sempre.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import advanced_tweaks as at  # noqa: E402
import optimization_engine as oe  # noqa: E402
import safe_tweaks as st  # noqa: E402
import session_owner as so  # noqa: E402
from fake_winreg import FakeWinreg  # noqa: E402

try:
    import tkinter as tk
    import optimization_ui as ou
    from tk_helpers import track_tk_root
except ImportError:  # Python sem Tk: os testes de tela pulam.
    tk = ou = track_tk_root = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))

MOUSE = r'Control Panel\Mouse'
NAMES = ('MouseSpeed', 'MouseThreshold1', 'MouseThreshold2')
SZ = FakeWinreg.REG_SZ
THEMES = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
GUID = '381b4222-f694-41f0-9685-ff5bb260df2e'


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _function(name):
    tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


class FakePower:
    kind = oe.POWER_KIND
    label = 'Plano de energia'

    def available(self):
        return [{'guid': GUID, 'name': 'Equilibrado', 'active': True}]

    def read(self, key):
        return GUID

    def apply(self, key, value):
        raise AssertionError('plano de energia não faz parte deste teste')

    revert = apply


class SourceTests(unittest.TestCase):
    def test_flow_uses_job_account_check_and_confirmation(self):
        # Critério 9: ler e aplicar rodam num Job, nunca na thread da tela.
        start = ast.unparse(_function('apply_advanced'))
        self.assertIn('self._is_elevated()', start)
        self.assertIn('self._run_power_job', start)
        # FIX-M3-T3: o Job do aplicar usa a mesma leitura e só depois confere o ponto.
        self.assertIn('self._checked_read_advanced_for_apply_work', start)
        for_apply = ast.unparse(_function('_checked_read_advanced_for_apply_work'))
        self.assertLess(for_apply.index('self._checked_read_advanced_work()'),
                        for_apply.index('self._reuse_at_for_apply()'))
        self.assertNotIn('read_states', start)
        refresh = ast.unparse(_function('refresh_advanced'))
        self.assertIn('self._run_power_job(self._checked_read_advanced_work', refresh)
        work = ast.unparse(_function('_checked_read_advanced_work'))
        self.assertLess(work.index('session_owner.session_owner'), work.index('_read_advanced_work()'))
        ready = ast.unparse(_function('_advanced_ready'))
        self.assertLess(ready.index('_advanced_account_refused'), ready.index('self._ask_advanced'))
        self.assertLess(ready.index('self._ask_advanced'), ready.index('apply_batch'))
        self.assertIn('self._run_power_job', ready)
        for name in ('apply_advanced', '_advanced_ready', '_advanced_apply_done', 'refresh_advanced',
                     '_build_advanced', '_render_advanced'):
            code = ast.unparse(_function(name))
            for forbidden in ('powercfg', 'subprocess', 'winreg', 'RunAs', 'Defender', 'webbrowser',
                              'SystemParametersInfo'):
                self.assertNotIn(forbidden, code)

    def test_labels(self):
        if ou is None:
            self.skipTest('sem Tk')
        self.assertEqual(at.CHANGES_TAB_NAME, ou.CHANGES_TAB_LABEL)
        self.assertEqual(ou.ADVANCED_TAB_LABEL, '9  Ajustes avançados')
        self.assertIn(ou.ADVANCED_TAB_LABEL, ou.TWEAKS_JOURNAL_OFF_TEXT)


@unittest.skipIf(NO_DISPLAY, 'sem Tk ou sem tela')
class AdvancedTabTests(unittest.TestCase):
    def setUp(self):
        for name in ('_run', '_ps'):
            patcher = mock.patch.object(oe, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.reg = FakeWinreg()
        self.adapter = at.AdvancedRegistryAdapter(registry=self.reg)
        self.safe_adapter = st.RegistryTweakAdapter(registry=self.reg)
        # P3-05 fatia 2: o ajuste do computador usa outro registro falso (só HKLM, vazio aqui).
        self.machine_reg = FakeWinreg(hives=('HKLM',))
        self.machine = at.MachineDwordAdapter(registry=self.machine_reg)
        self.admin = True
        self.owner = so.SAME
        self.owner_threads = []
        self.restore_ok = True
        self.restore_calls = []
        self.answer = True
        self.asked = []
        self.shown = []
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)
        self.panel = self.make_panel()
        self.addCleanup(self._join)  # R-29: roda antes da limpeza da pasta.

    def make_panel(self, **extra):
        options = dict(app_dir=self.tmp, state_dir=self.tmp, power_adapter=FakePower(),
                       tweak_adapter=self.safe_adapter, advanced_adapter=self.adapter,
                       machine_adapter=self.machine,
                       restore_point=self._restore_point, elevated_probe=lambda: self.admin,
                       session_owner_probe=self._owner, ask=self._ask,
                       show=lambda *a: self.shown.append(a))
        options.update(extra)
        panel = ou.OptimizationPanel(self.root, **options)
        panel.pack()
        self.settle(panel)
        return panel

    def _owner(self):
        self.owner_threads.append(threading.current_thread() is threading.main_thread())
        if isinstance(self.owner, Exception):
            raise self.owner
        return self.owner

    def _restore_point(self, description):
        self.restore_calls.append(description)
        return self.restore_ok

    def _ask(self, title, text):
        self.asked.append((title, text))
        return self.answer

    def _join(self):
        for name in ('_power_job', '_measure_job', '_checkup_job', '_idle_job', '_history_job'):
            job = getattr(self.panel, name, None)
            if job is not None:
                job.thread.join(timeout=5)

    def settle(self, panel=None):
        panel = panel or self.panel
        deadline = time.monotonic() + 5
        while (panel.power_busy or panel._history_job is not None) and time.monotonic() < deadline:
            job = panel._power_job
            if job is not None:
                job.thread.join(timeout=0.05)
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(panel.power_busy)
        self.assertIsNone(panel._history_job)

    def windows_default(self):
        for name, value in zip(NAMES, ('1', '6', '10')):
            self.reg.put(MOUSE, name, value, SZ)

    def values(self):
        return tuple(self.reg.get(MOUSE, name) for name in NAMES)

    def text(self):
        return self.panel.advanced_text.get('1.0', 'end')

    def writes(self):
        return [c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue', 'CreateKeyEx')]

    def apply(self):
        self.panel.apply_advanced('mouse_precision')
        self.settle()

    # ---------- abrir a aba ----------
    def test_tab_nine_lists_the_tweak_without_reading_the_registry(self):
        names = [self.panel.tabs.tab(t, 'text') for t in self.panel.tabs.tabs()]
        self.assertEqual(len(names), 9)
        self.assertEqual(names[8], '9  Ajustes avançados')
        self.assertEqual(names[7], ou.TWEAKS_TAB_LABEL)
        self.assertEqual(names[6], ou.CHANGES_TAB_LABEL)
        self.assertEqual(self.reg.calls, [])
        self.assertEqual(self.machine_reg.calls, [])
        tweak = at.TWEAKS_BY_ID['mouse_precision']
        text = self.text()
        for part in (tweak.name, tweak.what, tweak.downside, tweak.when,
                     ou.ADVANCED_NOT_READ_TEXT, ou.ADVANCED_UNDO_WHERE_TEXT):
            self.assertIn(part, text)
        self.assertEqual(self.restore_calls, [])

    def test_one_button_per_tweak(self):
        # Critério 5: botão próprio por ajuste.
        self.assertEqual(list(self.panel.advanced_buttons), [t.id for t in at.ADVANCED_TWEAKS])
        button = self.panel.advanced_buttons['mouse_precision']
        self.assertEqual(button.cget('text'), 'Aplicar: Aceleração do mouse desligada')
        self.assertFalse(button.instate(['disabled']))
        self.assertNotEqual(button, self.panel.btn_tweaks_apply)
        self.windows_default()
        button.invoke()
        self.settle()
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.values(), (('0', SZ),) * 3)

    def test_refresh_reads_in_a_job_and_shows_state(self):
        main = threading.current_thread()
        threads = []
        real = self.reg.OpenKey

        def spy(*args, **kwargs):
            threads.append(threading.current_thread() is main)
            return real(*args, **kwargs)
        self.reg.OpenKey = spy
        self.windows_default()
        self.panel.refresh_advanced()
        self.settle()
        self.assertTrue(threads)
        self.assertNotIn(True, threads)
        self.assertEqual(self.owner_threads, [False])
        self.assertIn('• Aceleração do mouse desligada: ainda não aplicado.', self.text())
        # Registro do computador vazio: o 2º ajuste aparece com o texto neutro de "não mexe" (R-57).
        self.assertIn('• Agendamento de GPU acelerado por hardware ligado: '
                      + at.STATE_TEXT['unsupported'], self.text())
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.asked, [])

    # ---------- aplicar ----------
    def test_apply_asks_with_downside_and_undo_all_brings_old_texts_back(self):
        # Critérios 3, 5 e 8.
        self.windows_default()
        main = threading.current_thread()
        threads = []
        real = self.reg.SetValueEx

        def spy(*args, **kwargs):
            threads.append(threading.current_thread() is main)
            return real(*args, **kwargs)
        self.reg.SetValueEx = spy
        self.apply()
        self.assertEqual(len(self.asked), 1)
        title, question = self.asked[0]
        tweak = at.TWEAKS_BY_ID['mouse_precision']
        self.assertEqual(title, ou.ADVANCED_TITLE)
        self.assertIn('Lado ruim: ' + tweak.downside, question)
        self.assertIn(tweak.when, question)
        self.assertIn('ponto de restauração', question)
        self.assertEqual(len(self.restore_calls), 1)
        self.assertEqual(self.values(), (('0', SZ),) * 3)
        self.assertTrue(threads)
        self.assertNotIn(True, threads)   # critério 9: grava no Job
        info = self.shown[-1]
        self.assertEqual(info[0], 'info')
        self.assertIn('sair da sua conta', info[2])
        self.assertIn('Desfazer tudo', info[2])
        self.assertIn('• Aceleração do mouse desligada: já aplicado.', self.text())
        changes = self.panel.changes_text.get('1.0', 'end')
        self.assertIn('Aceleração do mouse: aplicada.', changes)
        self.assertFalse(self.panel.btn_undo_all.instate(['disabled']))
        self.panel.undo_all_changes()
        self.settle()
        self.assertEqual(self.values(), (('1', SZ), ('6', SZ), ('10', SZ)))
        self.assertIn(ou.CHANGES_ONE_UNDONE_TEXT, self.panel.changes_status.get())
        self.assertIn('Aceleração do mouse: desfeita.', self.panel.changes_text.get('1.0', 'end'))
        self.assertIn('• Aceleração do mouse desligada: ainda não aplicado.', self.text())
        self.assertEqual(len(self.restore_calls), 1)

    def test_absent_values_are_deleted_on_undo_and_key_stays(self):
        self.reg.put(MOUSE, 'MouseSpeed', '1', SZ)
        self.apply()
        self.panel.undo_all_changes()
        self.settle()
        self.assertEqual(self.values(), (('1', SZ), None, None))
        self.assertIn(MOUSE.lower(), self.reg.keys)

    def test_recheck_covers_advanced_tweaks(self):
        self.windows_default()
        self.apply()
        self.windows_default()   # desfeito por fora, no Painel de Controle
        self.panel.recheck_changes()
        self.settle()
        self.assertEqual(self.panel.journal.entries()[0]['status'], 'reverted')
        self.assertIn(ou.CHANGES_RECHECK_FIXED_TEXT.format(n=1), self.panel.changes_status.get())
        self.assertIn('• Aceleração do mouse desligada: ainda não aplicado.', self.text())

    def test_no_writes_nothing_and_no_restore_point(self):
        # Critério 5: "Não" não cria ponto de restauração nem grava nada.
        self.windows_default()
        self.answer = False
        self.apply()
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.restore_calls, [])
        self.assertFalse(self.panel.journal.entries())
        self.assertEqual(self.panel.advanced_status.get(), ou.ADVANCED_CANCEL_TEXT)

    def test_only_a_real_yes_goes_on(self):
        self.windows_default()
        self.panel._ask_advanced = lambda title, text: 'yes'
        self.apply()
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.restore_calls, [])

    def test_default_question_comes_with_no_selected(self):
        # Critério 5: sem pergunta injetada, a janela do Windows vem com "Não" marcado.
        self.windows_default()
        panel = self.make_panel(ask=None)
        self.addCleanup(panel.destroy)
        with mock.patch.object(ou.messagebox, 'askyesno', return_value=False) as asked:
            panel.apply_advanced('mouse_precision')
            self.settle(panel)
        self.assertEqual(asked.call_count, 1)
        self.assertEqual(asked.call_args.kwargs.get('default'), ou.messagebox.NO)
        self.assertEqual(asked.call_args.kwargs.get('default'), 'no')
        self.assertIn('Lado ruim', asked.call_args.args[1])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.restore_calls, [])

    def test_already_applied_does_not_ask(self):
        for name in NAMES:
            self.reg.put(MOUSE, name, '0', SZ)
        self.apply()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.shown[-1], ('info', ou.ADVANCED_TITLE, ou.ADVANCED_ALREADY_TEXT))

    def test_other_type_is_not_touched(self):
        # Critério 2 na tela.
        self.windows_default()
        self.reg.put(MOUSE, 'MouseThreshold2', 10, FakeWinreg.REG_DWORD)
        self.apply()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.ADVANCED_NOT_TOUCHED_TEXT))
        self.assertIn('o app não mexe', self.text())

    def test_unreadable_is_not_touched_and_message_is_fixed(self):
        self.windows_default()
        self.reg.fail_read.add('MouseSpeed')
        self.apply()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.ADVANCED_READ_FAILED_TEXT))
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown)) + self.text())

    # ---------- critério 6: administrador e conta ----------
    def test_without_admin_explains_and_reads_nothing(self):
        self.admin = False
        self.apply()
        self.assertEqual(self.reg.calls, [])
        self.assertEqual(self.machine_reg.calls, [])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.TWEAKS_ADMIN_TEXT))

    def assert_refused_without_reading(self, expected):
        self.assertIsNotNone(self.panel._power_job)
        self.assertEqual(self.reg.calls, [])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertIsNone(self.panel.advanced_states)
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, expected))
        self.assertEqual(self.panel.advanced_status.get(), expected)
        self.assertFalse(self.panel.journal.entries())

    def test_other_account_refuses_before_reading(self):
        self.owner = so.OTHER
        self.apply()
        self.assert_refused_without_reading(ou.TWEAKS_OTHER_ACCOUNT_TEXT)
        self.panel.refresh_advanced()
        self.settle()
        self.assert_refused_without_reading(ou.TWEAKS_OTHER_ACCOUNT_TEXT)
        self.assertEqual(self.owner_threads, [False, False])

    def test_unknown_account_refuses_before_reading(self):
        for answer in (so.UNKNOWN, OSError('falhou'), 'qualquer coisa'):
            with self.subTest(answer=answer):
                self.owner = answer
                self.apply()
                self.assert_refused_without_reading(ou.TWEAKS_ACCOUNT_UNKNOWN_TEXT)
                self.panel.refresh_advanced()
                self.settle()
                self.assert_refused_without_reading(ou.TWEAKS_ACCOUNT_UNKNOWN_TEXT)

    def test_failed_job_counts_as_unknown_account(self):
        self.panel._advanced_ready({'status': 'error'}, at.TWEAKS_BY_ID['mouse_precision'])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.TWEAKS_ACCOUNT_UNKNOWN_TEXT))

    def test_unknown_entry_in_journal_blocks_before_reading(self):
        self.windows_default()
        self.apply()
        path = self.tmp / 'otimizacao-diario.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['entries'][0]['status'] = 'unknown'
        path.write_text(json.dumps(data), encoding='utf-8')
        panel = self.make_panel()
        self.addCleanup(panel.destroy)
        for tweak_id, button in panel.advanced_buttons.items():   # R-58: todos os botões
            with self.subTest(tweak=tweak_id):
                self.assertTrue(button.instate(['disabled']))
                calls, machine_calls = len(self.reg.calls), len(self.machine_reg.calls)
                asked, shown = len(self.asked), len(self.shown)
                job_before = panel._power_job
                panel.apply_advanced(tweak_id)
                self.assertIs(panel._power_job, job_before)
                self.assertEqual(len(self.reg.calls), calls)
                self.assertEqual(len(self.machine_reg.calls), machine_calls)
                self.assertEqual(len(self.asked), asked)
                self.assertEqual(len(self.shown), shown + 1)
                self.assertEqual(self.shown[-1][2], ou.ADVANCED_UNKNOWN_TEXT.format(n=1))
        calls, asked = len(self.reg.calls), len(self.asked)
        job_before = panel._power_job
        panel.apply_advanced('mouse_precision')
        self.assertIs(panel._power_job, job_before)
        self.assertEqual(len(self.reg.calls), calls)
        self.assertEqual(len(self.asked), asked)
        self.assertEqual(self.shown[-1][2], ou.ADVANCED_UNKNOWN_TEXT.format(n=1))

    # ---------- critério 7: ponto de restauração ----------
    def test_restore_point_refused_writes_nothing(self):
        self.windows_default()
        self.restore_ok = False
        self.apply()
        self.assertEqual(len(self.restore_calls), 1)
        self.assertFalse([c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue')])
        self.assertEqual(self.values(), (('1', SZ), ('6', SZ), ('10', SZ)))
        message = self.shown[-1][2]
        self.assertIn('ponto de restauração', message)
        self.assertIn(ou.POWER_RESTORE_POINT_HELP, message)
        self.assertFalse(self.panel.journal.entries())

    # ---------- falhas ----------
    def test_failure_on_third_value_rolls_back(self):
        # Critério 4 na tela.
        self.windows_default()
        self.reg.fail_set.add('MouseThreshold2')
        self.apply()
        self.assertEqual(self.values(), (('1', SZ), ('6', SZ), ('10', SZ)))
        self.assertEqual(self.shown[-1][0], 'warning')
        self.assertIn('desfeitos', self.shown[-1][2])
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown)))
        self.assertEqual(self.panel.journal.entries()[0]['status'], 'failed')

    def test_unexpected_error_turns_journal_off_until_reopen(self):
        self.windows_default()
        with mock.patch.object(self.panel.journal, 'apply_batch',
                               side_effect=RuntimeError(r'C:\Users\Fulano\segredo')):
            self.apply()
        message = ou.ADVANCED_UNEXPECTED_ERROR_TEXT
        self.assertIn('pode já ter mudado no Windows', message)
        self.assertNotIn('Nada foi', message)
        self.assertEqual(self.shown[-1], ('error', ou.ADVANCED_TITLE, message))
        self.assertEqual(self.panel.advanced_status.get(), message)
        self.assertIsNone(self.panel.journal)
        self.assertIsNone(self.panel.journal_off_text)
        self.assertEqual(list(self.panel.advanced_buttons), [t.id for t in at.ADVANCED_TWEAKS])
        for button in (*self.panel.advanced_buttons.values(), self.panel.btn_tweaks_apply,
                       self.panel.btn_undo_all, self.panel.btn_recheck):
            self.assertTrue(button.instate(['disabled']))
        self.assertFalse(self.panel.btn_advanced_refresh.instate(['disabled']))
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown)))
        for tweak_id in self.panel.advanced_buttons:   # R-58: todos os botões do grupo
            with self.subTest(tweak=tweak_id):
                asked, job = len(self.asked), self.panel._power_job
                self.panel.apply_advanced(tweak_id)
                self.assertEqual(len(self.asked), asked)
                self.assertIs(self.panel._power_job, job)
                self.assertEqual(self.shown[-1], ('error', ou.ADVANCED_TITLE, message))

    def test_journal_error_lists_the_buttons_that_turn_off(self):
        self.windows_default()
        with mock.patch.object(self.panel.journal, 'apply_batch',
                               side_effect=ou.JournalError('Não foi possível gravar o diário de alterações.')):
            self.apply()
        message = 'Não foi possível gravar o diário de alterações. ' + ou.ADVANCED_JOURNAL_OFF_TEXT
        self.assertEqual(self.shown[-1], ('error', ou.ADVANCED_TITLE, message))
        self.assertIsNone(self.panel.journal)
        for tweak_id, button in self.panel.advanced_buttons.items():   # R-58
            with self.subTest(tweak=tweak_id):
                self.assertTrue(button.instate(['disabled']))
                asked, job = len(self.asked), self.panel._power_job
                self.panel.apply_advanced(tweak_id)
                self.assertEqual(len(self.asked), asked)
                self.assertIs(self.panel._power_job, job)
                self.assertEqual(self.shown[-1][0], 'error')
        self.assertTrue(self.panel.btn_tweaks_apply.instate(['disabled']))

    def test_reread_failure_after_apply_is_neutral(self):
        self.windows_default()
        real = self.panel._read_advanced_work
        answers = []

        def flaky():
            answers.append(1)
            return real() if len(answers) == 1 else {'advanced': None}
        self.panel._read_advanced_work = flaky
        self.apply()
        self.assertEqual(len(self.panel.journal.entries()), 1)
        text = self.text()
        self.assertIn(ou.ADVANCED_REREAD_FAILED_TEXT, text)
        self.assertNotIn('Nada foi mudado', text)
        self.assertNotIn('Nada foi mudado', ou.ADVANCED_REREAD_FAILED_TEXT)

    def test_reread_failure_after_undo_all_is_neutral(self):
        self.windows_default()
        self.apply()
        self.panel._read_advanced_work = lambda: {'advanced': None}
        self.panel.undo_all_changes()
        self.settle()
        self.assertIn(ou.CHANGES_ONE_UNDONE_TEXT, self.panel.changes_status.get())
        self.assertIn(ou.ADVANCED_REREAD_FAILED_TEXT, self.text())

    def test_undo_all_does_not_read_advanced_if_never_shown(self):
        # Abrir a aba nunca lê o registro; o "Desfazer tudo" só relê o que já foi mostrado.
        self.panel.tweak_states = None
        self.safe_adapter_calls = 0
        self.panel.apply_safe_tweaks()
        self.settle()
        self.reg.calls.clear()
        self.panel.undo_all_changes()
        self.settle()
        self.assertFalse([c for c in self.reg.calls if 'mouse' in str(c[1]).lower()])
        self.assertIn(ou.ADVANCED_NOT_READ_TEXT, self.text())

    # ---------- um de cada vez ----------
    def test_buttons_off_while_another_job_runs(self):
        release = threading.Event()
        started = threading.Event()
        real = self.adapter.read

        def slow(key):
            started.set()
            release.wait(5)
            return real(key)
        self.adapter.read = slow
        self.panel.refresh_advanced()
        self.assertTrue(started.wait(5))
        self.root.update()
        for button in self.panel.advanced_buttons.values():   # R-58: todos os botões
            self.assertTrue(button.instate(['disabled']))
        self.assertTrue(self.panel.btn_advanced_refresh.instate(['disabled']))
        self.assertTrue(self.panel.btn_tweaks_apply.instate(['disabled']))
        job = self.panel._power_job
        for tweak_id in self.panel.advanced_buttons:
            self.panel.apply_advanced(tweak_id)
            self.assertIs(self.panel._power_job, job)
        self.panel.apply_safe_tweaks()
        self.assertIs(self.panel._power_job, job)
        self.assertEqual(self.asked, [])
        release.set()
        self.settle()
        for button in self.panel.advanced_buttons.values():
            self.assertFalse(button.instate(['disabled']))
        self.assertFalse(self.panel.btn_advanced_refresh.instate(['disabled']))

    def test_unknown_tweak_id_does_nothing(self):
        job_before = self.panel._power_job
        self.panel.apply_advanced('outro')
        self.assertIs(self.panel._power_job, job_before)
        self.assertEqual(self.reg.calls, [])


if __name__ == '__main__':
    unittest.main()
