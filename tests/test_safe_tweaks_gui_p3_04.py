"""P3-04: aba "8  Ajustes seguros" com Tk de verdade.

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

import optimization_engine as oe  # noqa: E402
import pc_measure as pm  # noqa: E402
import safe_tweaks as st  # noqa: E402
from fake_winreg import FakeWinreg  # noqa: E402

try:
    import tkinter as tk
    import optimization_ui as ou
    from tk_helpers import track_tk_root
except ImportError:  # Python sem Tk: os testes de tela pulam.
    tk = ou = track_tk_root = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))

GAMEBAR = r'Software\Microsoft\GameBar'
CONFIG = r'System\GameConfigStore'
DVR = r'Software\Microsoft\Windows\CurrentVersion\GameDVR'
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
    def test_flow_uses_job_confirmation_and_one_batch(self):
        start = ast.unparse(_function('apply_safe_tweaks'))
        self.assertIn('self._is_elevated()', start)
        self.assertIn('self._run_power_job', start)
        self.assertNotIn('read_states', start)    # a leitura é no Job, não na tela
        ready = ast.unparse(_function('_tweaks_ready'))
        self.assertIn('self._ask', ready)
        self.assertIn('confirmation_text', ready)
        self.assertIn('apply_batch', ready)
        self.assertIn('self._run_power_job', ready)
        for name in ('apply_safe_tweaks', '_tweaks_ready', '_tweaks_apply_done', 'refresh_tweaks',
                     '_build_tweaks', '_render_tweaks'):
            code = ast.unparse(_function(name))
            for forbidden in ('powercfg', 'subprocess', 'winreg', 'RunAs', 'Defender', 'webbrowser'):
                self.assertNotIn(forbidden, code)

    def test_tab_name_in_safe_tweaks_matches(self):
        if ou is None:
            self.skipTest('sem Tk')
        self.assertEqual(st.CHANGES_TAB_NAME, ou.CHANGES_TAB_LABEL)
        self.assertEqual(ou.TWEAKS_TAB_LABEL, '8  Ajustes seguros')


@unittest.skipIf(NO_DISPLAY, 'sem Tk ou sem tela')
class SafeTweaksTabTests(unittest.TestCase):
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
        self.adapter = st.RegistryTweakAdapter(registry=self.reg)
        self.admin = True
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

    def make_panel(self):
        panel = ou.OptimizationPanel(self.root, app_dir=self.tmp, state_dir=self.tmp,
                                     power_adapter=FakePower(), tweak_adapter=self.adapter,
                                     restore_point=self._restore_point,
                                     elevated_probe=lambda: self.admin,
                                     ask=self._ask, show=lambda *a: self.shown.append(a))
        panel.pack()
        self.settle(panel)
        return panel

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

    def text(self):
        return self.panel.tweaks_text.get('1.0', 'end')

    def writes(self):
        return [c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue', 'CreateKeyEx')]

    # ---------- abrir a aba ----------
    def test_tab_lists_the_three_tweaks_without_reading_the_registry(self):
        names = [self.panel.tabs.tab(t, 'text') for t in self.panel.tabs.tabs()]
        self.assertEqual(names[-1], '8  Ajustes seguros')
        self.assertEqual(names[6], ou.CHANGES_TAB_LABEL)
        self.assertEqual(self.reg.calls, [])
        text = self.text()
        for tweak in st.SAFE_TWEAKS:
            self.assertIn(tweak.name, text)
            self.assertIn(tweak.when, text)
        self.assertIn(ou.TWEAKS_NOT_READ_TEXT, text)
        self.assertIn(ou.TWEAKS_UNDO_WHERE_TEXT, text)
        self.assertIn('Desfazer tudo', ou.TWEAKS_UNDO_WHERE_TEXT)
        self.assertEqual(self.panel.btn_tweaks_apply.cget('text'), 'Aplicar ajustes seguros')
        self.assertFalse(self.panel.btn_tweaks_apply.instate(['disabled']))
        self.assertFalse(self.panel.btn_tweaks_refresh.instate(['disabled']))
        self.assertEqual(self.restore_calls, [])

    def test_refresh_reads_in_a_job_and_shows_state(self):
        main = threading.current_thread()
        threads = []
        real = self.reg.OpenKey

        def spy(*args, **kwargs):
            threads.append(threading.current_thread() is main)
            return real(*args, **kwargs)
        self.reg.OpenKey = spy
        self.reg.put(THEMES, 'EnableTransparency', 0)
        self.panel.refresh_tweaks()
        self.settle()
        self.assertTrue(threads)
        self.assertNotIn(True, threads)
        text = self.text()
        self.assertIn('• Efeitos de transparência desligados: já aplicado.', text)
        self.assertIn('• Modo de Jogo ligado: ainda não aplicado.', text)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.asked, [])

    # ---------- aplicar ----------
    def test_one_click_applies_only_what_is_missing_and_undo_all_brings_it_back(self):
        self.reg.put(GAMEBAR, 'AutoGameModeEnabled', 1)
        self.reg.put(THEMES, 'EnableTransparency', 1)
        self.reg.put(THEMES, 'AppsUseLightTheme', 1)
        self.panel.apply_safe_tweaks()
        self.settle()
        self.assertEqual(len(self.asked), 1)
        question = self.asked[0][1]
        self.assertIn(st.TWEAKS_BY_ID['game_bar_capture'].name, question)
        self.assertIn(st.TWEAKS_BY_ID['transparency'].name, question)
        self.assertNotIn(st.TWEAKS_BY_ID['game_mode'].name, question)
        self.assertIn('ponto de restauração', question)
        self.assertIn('diário de alterações', question)
        self.assertEqual(len(self.restore_calls), 1)
        self.assertEqual(self.reg.get(CONFIG, 'GameDVR_Enabled'), (0, FakeWinreg.REG_DWORD))
        self.assertEqual(self.reg.get(DVR, 'AppCaptureEnabled'), (0, FakeWinreg.REG_DWORD))
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (0, FakeWinreg.REG_DWORD))
        # O Modo de Jogo já estava ligado: nem entrou no lote.
        self.assertEqual([e['key'] for e in self.panel.journal.entries()],
                         ['game_dvr', 'app_capture', 'transparency'])
        self.assertFalse([c for c in self.reg.calls if c[0] == 'SetValueEx' and c[2] == 'AutoGameModeEnabled'])
        info = self.shown[-1]
        self.assertEqual(info[0], 'info')
        self.assertIn('Vale na hora.', info[2])
        self.assertIn('feche e abra o jogo de novo', info[2])
        self.assertIn('Desfazer tudo', info[2])
        self.assertIn('• Efeitos de transparência desligados: já aplicado.', self.text())
        changes = self.panel.changes_text.get('1.0', 'end')
        self.assertIn('Efeitos de transparência: aplicada.', changes)
        self.assertIn('Gravação do Game Bar (jogos): aplicada.', changes)
        self.assertFalse(self.panel.btn_undo_all.instate(['disabled']))
        # "Desfazer tudo" da aba 7 também cobre os ajustes seguros.
        self.panel.undo_all_changes()
        self.settle()
        self.assertIsNone(self.reg.get(CONFIG, 'GameDVR_Enabled'))   # não existia antes
        self.assertIsNone(self.reg.get(DVR, 'AppCaptureEnabled'))
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (1, FakeWinreg.REG_DWORD))
        self.assertEqual(self.reg.get(THEMES, 'AppsUseLightTheme'), (1, FakeWinreg.REG_DWORD))
        self.assertIn(DVR.lower(), self.reg.keys)   # a chave nunca é apagada
        self.assertEqual(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'), (1, FakeWinreg.REG_DWORD))
        self.assertIn(ou.CHANGES_ALL_UNDONE_TEXT.format(n=3), self.panel.changes_status.get())
        self.assertIn('• Efeitos de transparência desligados: ainda não aplicado.', self.text())
        self.assertEqual(len(self.restore_calls), 1)

    def test_recheck_covers_safe_tweaks(self):
        self.panel.apply_safe_tweaks()
        self.settle()
        self.assertEqual(len(self.panel.journal.entries()), 4)
        del self.reg.keys[THEMES.lower()]['EnableTransparency']   # desfeito por fora
        self.panel.recheck_changes()
        self.settle()
        statuses = {e['key']: e['status'] for e in self.panel.journal.entries()}
        self.assertEqual(statuses['transparency'], 'reverted')
        self.assertEqual(statuses['game_mode'], 'applied')
        self.assertIn(ou.CHANGES_RECHECK_FIXED_TEXT.format(n=1), self.panel.changes_status.get())
        self.assertIn('• Efeitos de transparência desligados: ainda não aplicado.', self.text())

    def test_cancel_changes_nothing(self):
        self.answer = False
        self.panel.apply_safe_tweaks()
        self.settle()
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.restore_calls, [])
        self.assertFalse(self.panel.journal.entries())
        self.assertEqual(self.panel.tweaks_status.get(), ou.TWEAKS_CANCEL_TEXT)

    def test_nothing_missing_does_not_ask_nor_create_restore_point(self):
        self.reg.put(GAMEBAR, 'AutoGameModeEnabled', 1)
        self.reg.put(CONFIG, 'GameDVR_Enabled', 0)
        self.reg.put(DVR, 'AppCaptureEnabled', 0)
        self.reg.put(THEMES, 'EnableTransparency', 0)
        self.panel.apply_safe_tweaks()
        self.settle()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.shown[-1][2], ou.TWEAKS_NOTHING_TEXT)

    def test_other_type_tweak_is_left_out(self):
        self.reg.put(THEMES, 'EnableTransparency', '1', FakeWinreg.REG_SZ)
        self.panel.apply_safe_tweaks()
        self.settle()
        self.assertNotIn(st.TWEAKS_BY_ID['transparency'].name, self.asked[0][1])
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), ('1', FakeWinreg.REG_SZ))
        self.assertIn('outro tipo', self.text())
        self.assertNotIn('transparency', [e['key'] for e in self.panel.journal.entries()])

    def test_without_admin_explains_and_reads_nothing(self):
        self.admin = False
        self.panel.apply_safe_tweaks()
        self.settle()
        self.assertEqual(self.reg.calls, [])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.shown[-1][2], ou.TWEAKS_ADMIN_TEXT)
        self.assertIn('OUTRA conta', ou.TWEAKS_ADMIN_TEXT)

    def test_restore_point_refused_changes_nothing(self):
        self.restore_ok = False
        self.panel.apply_safe_tweaks()
        self.settle()
        self.assertEqual(len(self.restore_calls), 1)
        self.assertFalse([c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue')])
        message = self.shown[-1][2]
        self.assertIn('ponto de restauração', message)
        self.assertIn(ou.POWER_RESTORE_POINT_HELP, message)

    def test_failure_in_the_middle_rolls_back(self):
        self.reg.fail_set.add('AppCaptureEnabled')
        self.panel.apply_safe_tweaks()
        self.settle()
        self.assertIsNone(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'))
        self.assertIsNone(self.reg.get(CONFIG, 'GameDVR_Enabled'))
        self.assertIsNone(self.reg.get(THEMES, 'EnableTransparency'))
        self.assertEqual(self.shown[-1][0], 'warning')
        self.assertIn('desfeitos', self.shown[-1][2])
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown)))

    def test_unexpected_error_shows_generic_message(self):
        with mock.patch.object(self.panel.journal, 'apply_batch',
                               side_effect=RuntimeError(r'C:\Users\Fulano\segredo')):
            self.panel.apply_safe_tweaks()
            self.settle()
        self.assertEqual(self.shown[-1], ('error', ou.TWEAKS_TITLE, ou.TWEAKS_GENERIC_FAIL))
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown)))
        self.assertNotIn('Fulano', self.panel.tweaks_status.get())

    def test_unknown_entry_blocks_before_asking(self):
        self.panel.apply_safe_tweaks()
        self.settle()
        entries = self.panel.journal.entries()
        data = json.loads((self.tmp / 'otimizacao-diario.json').read_text(encoding='utf-8'))
        data['entries'][0]['status'] = 'unknown'
        (self.tmp / 'otimizacao-diario.json').write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(len(entries), 4)
        panel = self.make_panel()
        self.assertTrue(panel.btn_tweaks_apply.instate(['disabled']))
        asked = len(self.asked)
        panel.apply_safe_tweaks()
        self.assertEqual(len(self.asked), asked)
        self.assertEqual(self.shown[-1][2], ou.TWEAKS_UNKNOWN_TEXT.format(n=1))
        panel.destroy()

    # ---------- um de cada vez ----------
    def test_buttons_off_while_applying_and_other_tasks_wait(self):
        release = threading.Event()
        started = threading.Event()
        real = self.adapter.read

        def slow(key):
            started.set()
            release.wait(5)
            return real(key)
        self.adapter.read = slow
        self.panel.refresh_tweaks()
        self.assertTrue(started.wait(5))
        self.root.update()
        self.assertTrue(self.panel.btn_tweaks_apply.instate(['disabled']))
        self.assertTrue(self.panel.btn_tweaks_refresh.instate(['disabled']))
        self.assertTrue(self.panel.btn_undo_all.instate(['disabled']))
        job = self.panel._power_job
        self.panel.apply_safe_tweaks()
        self.panel.refresh_tweaks()
        self.assertIs(self.panel._power_job, job)
        self.assertEqual(self.asked, [])
        release.set()
        self.settle()
        self.assertFalse(self.panel.btn_tweaks_apply.instate(['disabled']))
        self.assertFalse(self.panel.btn_tweaks_refresh.instate(['disabled']))

    def test_buttons_off_while_measuring(self):
        release = threading.Event()

        def slow(*args, **kwargs):
            release.wait(5)
            return {'cpu': 20, 'memory': 60, 'processes': 200, 'startup': 10, 'power_plan': 'Equilibrado'}
        with mock.patch.object(pm, 'read_measure', side_effect=slow):
            self.panel.measure_pc('antes')
            job = self.panel._measure_job
            self.assertIsNotNone(job)
            self.root.update()
            self.assertTrue(self.panel.btn_tweaks_apply.instate(['disabled']))
            self.assertTrue(self.panel.btn_tweaks_refresh.instate(['disabled']))
            power_job = self.panel._power_job
            self.panel.apply_safe_tweaks()
            self.panel.refresh_tweaks()
            self.assertIs(self.panel._power_job, power_job)
            self.assertEqual(self.reg.calls, [])
            release.set()
            job.thread.join(timeout=5)
            deadline = time.monotonic() + 5
            while self.panel._measure_job is not None and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
        self.assertFalse(self.panel.btn_tweaks_apply.instate(['disabled']))
        self.assertFalse(self.panel.btn_tweaks_refresh.instate(['disabled']))


if __name__ == '__main__':
    unittest.main()
