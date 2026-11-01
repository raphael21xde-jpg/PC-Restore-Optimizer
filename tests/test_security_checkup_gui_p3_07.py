"""P3-07 fatia 1: botão "Check-up de segurança" na aba "1 Diagnóstico".

Tk real com ``read_checkup`` simulado: nenhum PowerShell, registro, WMI ou
subprocess de verdade. Sem Tk (ou sem tela) os testes de janela pulam; os de
código-fonte e o de janela com Tk falso rodam sempre.
"""
import ast
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import optimization_engine as oe  # noqa: E402
import security_checkup as sc  # noqa: E402
from tk_helpers import track_tk_root  # noqa: E402

try:
    import tkinter as tk
    import optimization_ui as ou
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ou = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))
ENV = {'USERPROFILE': r'C:\Users\Fulano', 'SystemRoot': r'C:\Windows'}


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _result():
    return {'autostart': [{'source': 'run_user', 'name': 'Falso',
                           'path': r'%USERPROFILE%\AppData\Roaming\svchost.exe',
                           'state': sc.STATE_SUSPECT, 'reason': sc.REASON_SYSTEM_NAME, 'count': 1}],
            'processes': [], 'unchecked': 0, 'errors': []}


def _function(name):
    tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


class SourceTests(unittest.TestCase):
    def test_engine_has_no_tk_and_no_direct_commands(self):
        tree = ast.parse((ROOT / 'security_checkup.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        self.assertNotIn('tkinter', imported)
        self.assertNotIn('subprocess', imported)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for name in calls:
            self.assertFalse(name.startswith(('subprocess', 'os.system', 'os.popen', 'os.startfile')), name)

    def test_button_and_handlers_are_wired(self):
        build = ast.unparse(_function('_build_diagnostics'))
        self.assertIn("text='Check-up de segurança'", build)
        self.assertIn('command=self.security_checkup', build)
        start = ast.unparse(_function('security_checkup'))
        self.assertIn('CHECKUP_CONFIRMATION', start)
        self.assertIn('self._ask', start)
        self.assertIn("self.btn_checkup.configure(state='disabled')", start)
        self.assertIn('Job(', start)
        self.assertIn('self._timers.after', start)
        for name in ('security_checkup', '_checkup_finished', '_checkup_failed', 'show_checkup'):
            code = ast.unparse(_function(name))
            for forbidden in ('Stop-Process', 'Remove-', 'MpPreference', 'RunAs', 'subprocess',
                              'webbrowser', 'startfile', 'http'):
                self.assertNotIn(forbidden, code)


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def pack(self, *args, **kwargs):
        return None

    def configure(self, *args, **kwargs):
        return None

    def yview(self, *args):
        return None

    def set(self, *args):
        return None


class _FakeToplevel(_FakeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alive = True
        self.destroyed = 0

    def title(self, *args):
        return None

    def winfo_exists(self):
        return self.alive

    def destroy(self):
        self.destroyed += 1
        self.alive = False


class _FakeButton(_FakeWidget):
    created = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _FakeButton.created.append(self)


class ShowCheckupWithoutTkTests(unittest.TestCase):
    """R-18 sem Tk: executa show_checkup (lido com ast) com tk/ttk falsos."""

    def setUp(self):
        module = ast.Module(body=[_function('show_checkup')], type_ignores=[])
        _FakeButton.created = []
        fake_tk = types.SimpleNamespace(Toplevel=_FakeToplevel, Frame=_FakeWidget, Text=_FakeWidget)
        fake_ttk = types.SimpleNamespace(Scrollbar=_FakeWidget, Button=_FakeButton)
        namespace = {'tk': fake_tk, 'ttk': fake_ttk, 'BG': '#000', 'PANEL': '#111', 'TEXT': '#fff',
                     'checkup_engine': sc}
        exec(compile(module, 'optimization_ui.py', 'exec'), namespace)
        self.show = namespace['show_checkup']
        self.written = []
        self.panel = types.SimpleNamespace(_write=lambda widget, text: self.written.append(text))

    def test_opening_again_closes_previous(self):
        first = self.show(self.panel, _result())
        second = self.show(self.panel, _result())
        self.assertEqual(first.destroyed, 1)
        self.assertEqual(second.destroyed, 0)
        self.assertIs(self.panel._checkup_window, second)

    def test_close_button_and_text(self):
        window = self.show(self.panel, _result())
        close = [b for b in _FakeButton.created if b.kwargs.get('text') == 'Fechar']
        self.assertEqual(len(close), 1)
        close[0].kwargs['command']()
        self.assertEqual(window.destroyed, 1)
        self.assertIn(sc.RECOMMENDATION, self.written[-1])
        self.assertIn('[suspeito] Falso', self.written[-1])


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class CheckupButtonTests(unittest.TestCase):
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
        self.answer = True
        self.asked = []
        self.shown = []
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)
        self.panel = ou.OptimizationPanel(self.root, app_dir=self.tmp, state_dir=self.tmp,
                                          ask=self._ask, show=lambda *a: self.shown.append(a))
        self.panel.pack()
        # Leituras que o painel faz sozinho (planos de energia) terminam antes do teste.
        self._wait_power()
        self.addCleanup(self._join_checkup)  # R-29: roda antes da limpeza da pasta.

    def _ask(self, title, text):
        self.asked.append((title, text))
        return self.answer

    def _wait_power(self):
        deadline = time.monotonic() + 5
        while self.panel.power_busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)

    def _join_checkup(self):
        job = getattr(self.panel, '_checkup_job', None)
        if job is not None:
            job.thread.join(timeout=5)
            self.assertFalse(job.thread.is_alive())

    def _wait_finished(self, job):
        """R-06: espera a thread terminar e a tela mostrar o fim."""
        job.thread.join(timeout=5)
        self.assertFalse(job.thread.is_alive())
        deadline = time.monotonic() + 5
        while self.panel._checkup_job is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.panel._checkup_job)

    def test_button_exists_and_starts_enabled(self):
        button = self.panel.btn_checkup
        self.assertEqual(button.cget('text'), 'Check-up de segurança')
        self.assertFalse(button.instate(['disabled']))

    def test_cancel_does_not_query(self):
        self.answer = False
        with mock.patch.object(ou.checkup_engine, 'read_checkup', side_effect=_forbidden) as read:
            self.panel.security_checkup()
        read.assert_not_called()
        self.assertEqual(self.asked[0][1], sc.CHECKUP_CONFIRMATION)
        self.assertIn('tarefas agendadas', self.asked[0][1])  # P3-07 fatia 2
        self.assertIsNone(self.panel._checkup_job)
        self.assertIsNone(getattr(self.panel, '_checkup_window', None))
        self.assertFalse(self.panel.btn_checkup.instate(['disabled']))
        self.assertIn('Nada foi lido', self.panel.note.get())

    def test_confirm_opens_window_and_button_disabled_while_running(self):
        release = threading.Event()
        started = threading.Event()

        def slow(*args, **kwargs):
            started.set()
            release.wait(5)
            return _result()
        with mock.patch.object(ou.checkup_engine, 'read_checkup', side_effect=slow) as read:
            self.panel.security_checkup()
            job = self.panel._checkup_job
            self.assertIsNotNone(job)
            self.assertTrue(started.wait(5))
            self.assertTrue(self.panel.btn_checkup.instate(['disabled']))
            self.panel.security_checkup()  # segundo clique não abre outra consulta
            self.assertIs(self.panel._checkup_job, job)
            self.assertEqual(len(self.asked), 1)
            self.root.update()
            self.assertTrue(self.panel.btn_checkup.instate(['disabled']))
            release.set()
            self._wait_finished(job)
        self.assertEqual(read.call_count, 1)
        self.assertFalse(self.panel.btn_checkup.instate(['disabled']))
        window = self.panel._checkup_window
        self.assertIsInstance(window, tk.Toplevel)
        texts = [g for w in window.winfo_children() for g in w.winfo_children() if isinstance(g, tk.Text)]
        self.assertEqual(len(texts), 1)
        self.assertEqual(str(texts[0].cget('state')), 'disabled')
        content = texts[0].get('1.0', 'end')
        self.assertIn('[suspeito] Falso', content)
        self.assertIn(sc.RECOMMENDATION, content)
        self.assertNotIn('Fulano', content)
        window.destroy()

    def test_failure_shows_generic_message_once(self):
        with mock.patch.object(ou.checkup_engine, 'read_checkup',
                               side_effect=RuntimeError(r'C:\Users\Fulano\segredo')):
            self.panel.security_checkup()
            self._wait_finished(self.panel._checkup_job)
        self.assertFalse(self.panel.btn_checkup.instate(['disabled']))
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(self.shown[0][2], ou.CHECKUP_FAILED_TEXT)
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown[0])))
        self.assertIsNone(getattr(self.panel, '_checkup_window', None))

    def test_opening_again_closes_previous_window(self):
        first = self.panel.show_checkup(_result())
        second = self.panel.show_checkup(_result())
        self.root.update()
        self.assertEqual(first.winfo_exists(), 0)
        self.assertEqual(second.winfo_exists(), 1)
        self.assertIs(self.panel._checkup_window, second)
        second.destroy()

    def test_close_button_closes_window(self):
        from tkinter import ttk
        window = self.panel.show_checkup(_result())
        buttons = [w for w in window.winfo_children()
                   if isinstance(w, ttk.Button) and w.cget('text') == 'Fechar']
        self.assertEqual(len(buttons), 1)
        buttons[0].invoke()
        self.root.update()
        self.assertEqual(window.winfo_exists(), 0)


if __name__ == '__main__':
    unittest.main()
