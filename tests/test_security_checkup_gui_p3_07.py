"""P3-07: botões "Check-up de segurança" e (fatia 4) "Medir uso parado (2 min)" na aba "1 Diagnóstico".

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

    def test_idle_button_and_handlers_are_wired(self):
        # P3-07 fatia 4: botão separado, pergunta antes, Job e retorno por WindowTimers.
        build = ast.unparse(_function('_build_diagnostics'))
        self.assertIn('text=IDLE_BUTTON_TEXT', build)
        self.assertIn('command=self.measure_idle', build)
        start = ast.unparse(_function('measure_idle'))
        self.assertIn('IDLE_CONFIRMATION', start)
        self.assertIn('self._ask', start)
        self.assertIn("state='disabled'", start)
        self.assertIn('IDLE_RUNNING_TEXT', start)
        self.assertIn('Job(', start)
        self.assertIn('read_idle', start)
        self.assertIn('self._timers.after', start)
        source = (ROOT / 'optimization_ui.py').read_text(encoding='utf-8')
        self.assertIn("IDLE_BUTTON_TEXT='Medir uso parado (2 min)'", source)
        self.assertIn("IDLE_RUNNING_TEXT='Medindo... (2 min)'", source)
        for name in ('measure_idle', '_idle_finished', '_idle_failed', '_idle_done'):
            code = ast.unparse(_function(name))
            for forbidden in ('Stop-Process', 'Remove-', 'RunAs', 'subprocess', 'webbrowser', 'startfile', 'http'):
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

    def test_defender_and_network_sections_in_window(self):
        # P3-07 fatia 3: as duas seções novas aparecem na janela e entram no RESUMO.
        result = dict(_result(), autostart=[],
                      defender=[{'source': 'defender', 'name': 'Microsoft Defender', 'kind': None, 'path': '',
                                 'state': sc.STATE_ATTENTION, 'reason': sc.REASON_RT_OFF, 'count': 1}],
                      network=[{'source': 'network', 'name': 'mina', 'path': '', 'port': 3333,
                                'state': sc.STATE_SUSPECT, 'reason': sc.REASON_MINING_PORT, 'count': 2}])
        self.show(self.panel, result)
        text = self.written[-1]
        self.assertIn('MICROSOFT DEFENDER', text)
        self.assertIn('CONEXÕES DE REDE', text)
        self.assertIn('[suspeito] mina (2 conexões) — porta 3333', text)
        self.assertIn('RESUMO: OK 0 · atenção 1 · suspeito 1', text)
        self.assertIn(sc.RECOMMENDATION, text)

    def test_idle_only_and_combined_window(self):
        # P3-07 fatia 4: a medição aparece na mesma janela, sozinha ou junto do check-up.
        idle = sc.classify_idle({'Cpu': [60], 'Gpu': [1], 'Top': ['mina']}, ENV)
        self.panel._idle_result = idle
        self.show(self.panel, {})
        alone = self.written[-1]
        self.assertIn('USO COM O PC PARADO — SÓ LEITURA', alone)
        self.assertIn('[atenção] Processador (CPU): média de 60%', alone)
        self.assertIn('mina', alone)
        self.assertIn(sc.RECOMMENDATION, alone)
        self.assertNotIn('PROCESSOS EM EXECUÇÃO', alone)
        self.show(self.panel, _result())
        both = self.written[-1]
        self.assertIn('PROCESSOS EM EXECUÇÃO', both)
        self.assertIn('USO COM O PC PARADO', both)
        self.assertIn('RESUMO: OK 1 · atenção 1 · suspeito 1', both)


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
        self.assertIn('Microsoft Defender', self.asked[0][1])  # P3-07 fatia 3
        self.assertIn('conexões de rede', self.asked[0][1])
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

    def _idle(self, cpu=60):
        return sc.classify_idle({'Cpu': [cpu], 'Gpu': [1], 'Top': ['mina']}, ENV)

    def _wait_idle(self, job):
        job.thread.join(timeout=5)
        self.assertFalse(job.thread.is_alive())
        deadline = time.monotonic() + 5
        while self.panel._idle_job is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.panel._idle_job)

    def _join_idle(self):
        job = getattr(self.panel, '_idle_job', None)
        if job is not None:
            job.thread.join(timeout=5)

    def test_idle_button_exists_next_to_checkup(self):
        button = self.panel.btn_idle
        self.assertEqual(button.cget('text'), 'Medir uso parado (2 min)')
        self.assertFalse(button.instate(['disabled']))
        self.assertIs(button.master, self.panel.btn_checkup.master)

    def test_idle_cancel_does_not_measure(self):
        self.answer = False
        with mock.patch.object(ou.checkup_engine, 'read_idle', side_effect=_forbidden) as read:
            self.panel.measure_idle()
        read.assert_not_called()
        self.assertEqual(self.asked[0][1], sc.IDLE_CONFIRMATION)
        self.assertIn('2 minutos', self.asked[0][1])
        self.assertIsNone(self.panel._idle_job)
        self.assertFalse(self.panel.btn_idle.instate(['disabled']))
        self.assertIn('Nada foi lido', self.panel.note.get())

    def test_idle_runs_in_job_and_shows_section(self):
        self.addCleanup(self._join_idle)
        release = threading.Event()
        started = threading.Event()

        def slow(*args, **kwargs):
            started.set()
            release.wait(5)
            return self._idle()
        with mock.patch.object(ou.checkup_engine, 'read_idle', side_effect=slow) as read:
            self.panel.measure_idle()
            job = self.panel._idle_job
            self.assertIsNotNone(job)
            self.assertTrue(started.wait(5))
            self.root.update()
            self.assertTrue(self.panel.btn_idle.instate(['disabled']))
            self.assertEqual(self.panel.btn_idle.cget('text'), 'Medindo... (2 min)')
            # Enquanto mede, o check-up (que usa o processador) não começa.
            self.assertTrue(self.panel.btn_checkup.instate(['disabled']))
            with mock.patch.object(ou.checkup_engine, 'read_checkup', side_effect=_forbidden) as check:
                self.panel.security_checkup()
                check.assert_not_called()
            self.panel.measure_idle()  # segundo clique não abre outra medição
            self.assertIs(self.panel._idle_job, job)
            self.assertEqual(len(self.asked), 1)
            release.set()
            self._wait_idle(job)
        self.assertEqual(read.call_count, 1)
        self.assertFalse(self.panel.btn_idle.instate(['disabled']))
        self.assertEqual(self.panel.btn_idle.cget('text'), 'Medir uso parado (2 min)')
        self.assertFalse(self.panel.btn_checkup.instate(['disabled']))
        window = self.panel._checkup_window
        self.assertIsInstance(window, tk.Toplevel)
        texts = [g for w in window.winfo_children() for g in w.winfo_children() if isinstance(g, tk.Text)]
        self.assertEqual(len(texts), 1)
        self.assertEqual(str(texts[0].cget('state')), 'disabled')
        content = texts[0].get('1.0', 'end')
        self.assertIn('USO COM O PC PARADO', content)
        self.assertIn(sc.IDLE_NOTE, content)
        self.assertIn(sc.RECOMMENDATION, content)
        window.destroy()

    def test_idle_after_checkup_shows_both_in_same_window(self):
        self.addCleanup(self._join_idle)
        with mock.patch.object(ou.checkup_engine, 'read_checkup', return_value=_result()):
            self.panel.security_checkup()
            self._wait_finished(self.panel._checkup_job)
        with mock.patch.object(ou.checkup_engine, 'read_idle', return_value=self._idle(cpu=3)):
            self.panel.measure_idle()
            self._wait_idle(self.panel._idle_job)
        window = self.panel._checkup_window
        texts = [g for w in window.winfo_children() for g in w.winfo_children() if isinstance(g, tk.Text)]
        content = texts[0].get('1.0', 'end')
        self.assertIn('[suspeito] Falso', content)
        self.assertIn('[OK] Processador (CPU): média de 3%', content)
        window.destroy()

    def test_idle_failure_shows_generic_message(self):
        self.addCleanup(self._join_idle)
        with mock.patch.object(ou.checkup_engine, 'read_idle', side_effect=RuntimeError(r'C:\Users\Fulano\x')):
            self.panel.measure_idle()
            self._wait_idle(self.panel._idle_job)
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(self.shown[0][2], ou.IDLE_FAILED_TEXT)
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown[0])))
        self.assertFalse(self.panel.btn_idle.instate(['disabled']))
        self.assertEqual(self.panel.btn_idle.cget('text'), 'Medir uso parado (2 min)')

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
