"""P3-05 fatia 2: botão do agendamento de GPU por hardware na aba "9  Ajustes avançados".

Tk de verdade, registros falsos em memória (HKCU e HKLM separados), ponto de
restauração falso e subprocess bloqueado. Nenhum registro, PowerShell ou
powercfg de verdade. Arquivos só em TemporaryDirectory. Sem Tk (ou sem tela)
os testes de janela pulam; os de código-fonte rodam sempre.
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

GRAPHICS = r'SYSTEM\CurrentControlSet\Control\GraphicsDrivers'
VERSION = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
HKLM = FakeWinreg.HKEY_LOCAL_MACHINE
DWORD = FakeWinreg.REG_DWORD
KEY = 'gpu_hw_scheduling'
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
    def test_machine_adapter_goes_to_the_journal_and_to_both_reads(self):
        self.assertIn('MACHINE_KIND: self.machine_adapter', ast.unparse(_function('_load_change_journal')))
        self.assertIn('read_states(self.advanced_adapter, self.machine_adapter)',
                      ast.unparse(_function('_read_advanced_work')))
        ready = ast.unparse(_function('_advanced_ready'))
        self.assertIn('read_states(adapter, machine_adapter)', ready)
        self.assertIn('self._advanced_state_message(state)', ready)
        self.assertIn('ADVANCED_UNSUPPORTED_TEXT', ast.unparse(_function('_advanced_state_message')))

    def test_intro_text_no_longer_says_only_your_account(self):
        if ou is None:
            self.skipTest('sem Tk')
        self.assertNotIn('Só na sua conta', ou.ADVANCED_INTRO_TEXT)
        self.assertIn('A maioria vale só na sua conta; o que vale para o computador inteiro avisa '
                      'na pergunta.', ou.ADVANCED_INTRO_TEXT)
        # R-57: texto neutro, igual ao do adaptador; não culpa o Windows nem a placa.
        self.assertEqual(ou.ADVANCED_UNSUPPORTED_TEXT, at.MSG_NOT_SUPPORTED)
        self.assertNotIn('não oferece', ou.ADVANCED_UNSUPPORTED_TEXT)
        self.assertIn('não reconheceu esta opção', ou.ADVANCED_UNSUPPORTED_TEXT)
        # R-59: o aviso não orienta ligar a opção por fora.
        self.assertNotIn('Configurações', ou.ADVANCED_UNSUPPORTED_TEXT)
        self.assertNotIn('ligue', ou.ADVANCED_UNSUPPORTED_TEXT.lower())

    def test_unchanged_message_follows_the_new_state(self):
        if ou is None:
            self.skipTest('sem Tk')
        message = ou.OptimizationPanel._advanced_state_message
        self.assertEqual(message('applied'), ou.ADVANCED_ALREADY_TEXT)
        self.assertEqual(message('unsupported'), ou.ADVANCED_UNSUPPORTED_TEXT)
        self.assertEqual(message('other_type'), ou.ADVANCED_NOT_TOUCHED_TEXT)
        for state in ('not_applied', 'unreadable', None):
            self.assertEqual(message(state), ou.ADVANCED_READ_FAILED_TEXT)
        done = ast.unparse(_function('_advanced_apply_done'))
        self.assertIn('self._advanced_state_message(state)', done)


@unittest.skipIf(NO_DISPLAY, 'sem Tk ou sem tela')
class GpuButtonTests(unittest.TestCase):
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
        self.machine_reg = FakeWinreg(hives=('HKLM',))
        self.admin = True
        self.owner = so.SAME
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
                       tweak_adapter=st.RegistryTweakAdapter(registry=self.reg),
                       advanced_adapter=at.AdvancedRegistryAdapter(registry=self.reg),
                       machine_adapter=at.MachineDwordAdapter(registry=self.machine_reg),
                       restore_point=self._restore_point, elevated_probe=lambda: self.admin,
                       session_owner_probe=self._owner, ask=self._ask,
                       show=lambda *a: self.shown.append(a))
        options.update(extra)
        panel = ou.OptimizationPanel(self.root, **options)
        panel.pack()
        self.settle(panel)
        return panel

    def _owner(self):
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

    def supported(self, mode=1, build='22631'):
        self.machine_reg.put(VERSION, 'CurrentBuildNumber', build, FakeWinreg.REG_SZ, hive=HKLM)
        self.machine_reg.put(GRAPHICS, 'HwSchMode', mode, DWORD, hive=HKLM)

    def current(self):
        return self.machine_reg.get(GRAPHICS, 'HwSchMode', hive=HKLM)

    def writes(self):
        return [c for c in self.machine_reg.calls + self.reg.calls
                if c[0] in ('SetValueEx', 'DeleteValue', 'CreateKeyEx')]

    def text(self):
        return self.panel.advanced_text.get('1.0', 'end')

    def apply(self):
        self.panel.apply_advanced(KEY)
        self.settle()

    def test_own_button_and_default_adapter(self):
        button = self.panel.advanced_buttons[KEY]
        self.assertEqual(button.cget('text'), 'Aplicar: Agendamento de GPU acelerado por hardware ligado')
        self.assertEqual(list(self.panel.advanced_buttons), ['mouse_precision', KEY])
        self.assertEqual(self.machine_reg.calls, [])   # abrir a aba não lê nada
        names = [self.panel.tabs.tab(t, 'text') for t in self.panel.tabs.tabs()]
        self.assertEqual(len(names), 9)
        panel = self.make_panel(machine_adapter=None)
        self.addCleanup(panel.destroy)
        self.assertIsInstance(panel.machine_adapter, at.MachineDwordAdapter)
        self.assertIs(panel.journal._adapters[at.MACHINE_KIND], panel.machine_adapter)

    def test_yes_applies_restart_message_and_undo_all_in_tab_7(self):
        self.supported()
        self.apply()
        self.assertEqual(len(self.asked), 1)
        title, question = self.asked[0]
        tweak = at.TWEAKS_BY_ID[KEY]
        self.assertEqual(title, ou.ADVANCED_TITLE)
        for part in ('todas as contas', 'reiniciar', 'Lado ruim: ' + tweak.downside, 'ponto de restauração'):
            self.assertIn(part, question)
        self.assertEqual(len(self.restore_calls), 1)
        self.assertEqual(self.current(), (2, DWORD))
        info = self.shown[-1]
        self.assertEqual(info[0], 'info')
        self.assertIn('reiniciar o computador', info[2])
        self.assertIn('Desfazer tudo', info[2])
        self.assertIn('• Agendamento de GPU acelerado por hardware ligado: já aplicado.', self.text())
        changes = self.panel.changes_text.get('1.0', 'end')
        self.assertIn('Agendamento de GPU por hardware: aplicada.', changes)
        self.assertEqual([c for c in self.reg.calls if c[0] == 'SetValueEx'], [])   # a conta não muda
        self.panel.undo_all_changes()
        self.settle()
        self.assertEqual(self.current(), (1, DWORD))
        self.assertIn(ou.CHANGES_ONE_UNDONE_TEXT, self.panel.changes_status.get())
        self.assertIn('Agendamento de GPU por hardware: desfeita.', self.panel.changes_text.get('1.0', 'end'))
        self.assertEqual(len(self.restore_calls), 1)

    def test_no_writes_nothing_and_no_restore_point(self):
        self.supported()
        self.answer = False
        self.apply()
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.restore_calls, [])
        self.assertFalse(self.panel.journal.entries())
        self.assertEqual(self.current(), (1, DWORD))
        self.assertEqual(self.panel.advanced_status.get(), ou.ADVANCED_CANCEL_TEXT)

    def test_without_admin_refuses_before_reading(self):
        self.supported()
        self.admin = False
        self.apply()
        self.assertEqual(self.machine_reg.calls, [])
        self.assertEqual(self.reg.calls, [])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.TWEAKS_ADMIN_TEXT))

    def test_unsupported_shows_a_warning_without_question(self):
        for case in ('old_build', 'no_value', 'three'):
            with self.subTest(case=case):
                self.machine_reg.machine_keys.clear()
                if case == 'old_build':
                    self.supported(build='18363')
                elif case == 'three':
                    self.supported(mode=3)
                else:
                    self.machine_reg.put(VERSION, 'CurrentBuildNumber', '22631', FakeWinreg.REG_SZ, hive=HKLM)
                self.machine_reg.calls.clear()
                self.shown.clear()
                self.apply()
                self.assertEqual(self.asked, [])
                self.assertEqual(self.restore_calls, [])
                self.assertEqual(self.writes(), [])
                self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.ADVANCED_UNSUPPORTED_TEXT))
                self.assertIn('• Agendamento de GPU acelerado por hardware ligado: '
                              + at.STATE_TEXT['unsupported'], self.text())
        self.assertFalse(self.panel.journal.entries())

    def test_other_or_unknown_account_refuses_before_reading_hklm(self):
        self.supported()
        for answer in (so.OTHER, so.UNKNOWN, OSError('falhou')):
            with self.subTest(answer=answer):
                self.owner = answer
                expected = (ou.TWEAKS_OTHER_ACCOUNT_TEXT if answer == so.OTHER
                            else ou.TWEAKS_ACCOUNT_UNKNOWN_TEXT)
                self.apply()
                self.assertEqual(self.machine_reg.calls, [])
                self.assertEqual(self.reg.calls, [])
                self.assertEqual(self.asked, [])
                self.assertEqual(self.restore_calls, [])
                self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, expected))
                self.panel.refresh_advanced()
                self.settle()
                self.assertEqual(self.machine_reg.calls, [])
        self.assertEqual(self.current(), (1, DWORD))

    def test_restore_point_refused_writes_nothing_in_hklm(self):
        self.supported()
        self.restore_ok = False
        self.apply()
        self.assertEqual(len(self.restore_calls), 1)
        self.assertFalse([c for c in self.machine_reg.calls if c[0] == 'SetValueEx'])
        self.assertEqual(self.current(), (1, DWORD))
        self.assertIn(ou.POWER_RESTORE_POINT_HELP, self.shown[-1][2])
        self.assertFalse(self.panel.journal.entries())

    def changed_while_asking(self, mode):
        def ask(title, text):
            self.asked.append((title, text))
            self.supported(mode=mode)   # mudado por fora enquanto a pergunta estava aberta
            return True
        self.panel._ask_advanced = ask

    def test_changed_to_out_of_list_while_asking_does_not_say_already_applied(self):
        self.supported()
        self.changed_while_asking(3)
        self.apply()
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.current(), (3, DWORD))
        self.assertEqual(self.panel.advanced_status.get(), ou.ADVANCED_UNSUPPORTED_TEXT)
        self.assertNotEqual(self.panel.advanced_status.get(), ou.ADVANCED_ALREADY_TEXT)
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.ADVANCED_UNSUPPORTED_TEXT))
        self.assertFalse(self.panel.journal.entries())

    def test_turned_on_outside_while_asking_says_already_applied(self):
        self.supported()
        self.changed_while_asking(2)
        self.apply()
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.panel.advanced_status.get(), ou.ADVANCED_ALREADY_TEXT)
        self.assertFalse(self.panel.journal.entries())

    def test_unknown_entry_in_journal_blocks_the_gpu_button_before_reading(self):
        self.supported()
        self.apply()
        path = self.tmp / 'otimizacao-diario.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['entries'][0]['status'] = 'unknown'
        path.write_text(json.dumps(data), encoding='utf-8')
        panel = self.make_panel()
        self.addCleanup(panel.destroy)
        self.assertTrue(panel.advanced_buttons[KEY].instate(['disabled']))
        self.machine_reg.calls.clear()
        self.reg.calls.clear()
        asked, restore = len(self.asked), len(self.restore_calls)
        job_before = panel._power_job
        panel.apply_advanced(KEY)
        self.assertIs(panel._power_job, job_before)
        self.assertEqual(self.machine_reg.calls, [])
        self.assertEqual(self.reg.calls, [])
        self.assertEqual(len(self.asked), asked)
        self.assertEqual(len(self.restore_calls), restore)
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.ADVANCED_UNKNOWN_TEXT.format(n=1)))
        self.assertEqual(self.current(), (2, DWORD))

    def test_hklm_write_failure_refuses_the_batch_and_marks_failed(self):
        self.supported()
        self.machine_reg.fail_set.add('HwSchMode')
        self.apply()
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(len(self.restore_calls), 1)
        self.assertEqual(self.current(), (1, DWORD))
        kind, title, message = self.shown[-1]
        self.assertEqual((kind, title), ('warning', ou.ADVANCED_TITLE))
        self.assertIn('desfeitos', message)
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown)))
        self.assertEqual(self.panel.journal.entries()[0]['status'], 'failed')
        self.assertIn('• Agendamento de GPU acelerado por hardware ligado: ainda não aplicado.', self.text())

    def test_undo_all_when_windows_version_is_no_longer_readable(self):
        # Revisão da PR #206: a versão do Windows deixa de ser lida depois de aplicar. O
        # adaptador recusa antes de gravar, então o ajuste continua aplicado; a tela diz que
        # continua como estava, nunca que foi desfeito, e a linha segue "applied" (R-27).
        self.supported()
        self.apply()
        self.assertEqual(self.current(), (2, DWORD))
        self.machine_reg.put(VERSION, 'CurrentBuildNumber', 'xx', FakeWinreg.REG_SZ, hive=HKLM)
        self.answer = True
        self.panel.undo_all_changes()
        self.settle()
        self.assertEqual(self.current(), (2, DWORD))   # nada foi trocado no registro
        self.assertEqual(self.writes()[-1][0], 'SetValueEx')   # só a gravação de aplicar
        self.assertEqual(len([c for c in self.writes() if c[0] == 'SetValueEx']), 1)
        status = self.panel.changes_status.get()
        self.assertTrue(status.startswith('0 desfeita(s); 1 continuam como estavam.'), status)
        self.assertNotIn(ou.CHANGES_ONE_UNDONE_TEXT, status)
        self.assertEqual(self.shown[-1], ('warning', 'Desfazer tudo', status))
        self.assertEqual(self.panel.journal.entries()[0]['status'], 'applied')
        self.assertNotIn('Agendamento de GPU por hardware: desfeita.',
                         self.panel.changes_text.get('1.0', 'end'))

    def test_already_on_does_not_ask(self):
        self.supported(mode=2)
        self.apply()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.shown[-1], ('info', ou.ADVANCED_TITLE, ou.ADVANCED_ALREADY_TEXT))


if __name__ == '__main__':
    unittest.main()
