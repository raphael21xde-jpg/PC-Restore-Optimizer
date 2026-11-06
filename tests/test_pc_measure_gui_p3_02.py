"""P3-02: bloco "Medição antes e depois" na aba "1 Diagnóstico".

Tk real com ``read_measure`` simulado: nenhum PowerShell, registro, WMI,
powercfg ou subprocess de verdade. Arquivos só em TemporaryDirectory. Sem Tk
(ou sem tela) os testes de janela pulam; os de código-fonte rodam sempre.
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

try:
    import tkinter as tk
    import optimization_ui as ou
    from tk_helpers import track_tk_root
except ImportError:  # Python sem Tk: os testes de tela pulam.
    tk = ou = track_tk_root = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _measure(**over):
    values = {'cpu': 20, 'memory': 60, 'processes': 200, 'startup': 10, 'power_plan': 'Equilibrado'}
    values.update(over)
    return values


def _function(name):
    tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


class SourceTests(unittest.TestCase):
    def test_block_and_handler_are_wired(self):
        build = ast.unparse(_function('_build_diagnostics'))
        self.assertIn('text=MEASURE_BEFORE_TEXT', build)
        self.assertIn('text=MEASURE_AFTER_TEXT', build)
        self.assertIn("self.measure_pc('antes')", build)
        self.assertIn("self.measure_pc('depois')", build)
        start = ast.unparse(_function('measure_pc'))
        self.assertIn('MEASURE_CONFIRMATION', start)
        self.assertIn('self._ask', start)
        self.assertIn('Job(', start)
        self.assertIn('read_measure', start)
        self.assertIn('save_measure', start)
        self.assertIn('self._timers.after', start)
        source = (ROOT / 'optimization_ui.py').read_text(encoding='utf-8')
        self.assertIn("MEASURE_BEFORE_TEXT='Medir ANTES (1 min)'", source)
        self.assertIn("MEASURE_AFTER_TEXT='Medir DEPOIS (1 min)'", source)
        for name in ('measure_pc', '_measure_done', '_render_measures'):
            code = ast.unparse(_function(name))
            for forbidden in ('powercfg', 'Stop-Process', 'Remove-', 'RunAs', 'subprocess', 'webbrowser',
                              'startfile', 'http'):
                self.assertNotIn(forbidden, code)

    def test_confirmation_says_read_only_one_minute_dont_use(self):
        self.assertIn('1 minuto', pm.MEASURE_CONFIRMATION)
        self.assertIn('Só lê', pm.MEASURE_CONFIRMATION)
        self.assertIn('Não use o PC', pm.MEASURE_CONFIRMATION)


@unittest.skipIf(NO_DISPLAY, 'sem Tk ou sem tela')
class MeasureBlockTests(unittest.TestCase):
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
        deadline = time.monotonic() + 5
        while self.panel.power_busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.addCleanup(self._join)  # R-29: roda antes da limpeza da pasta.

    def _ask(self, title, text):
        self.asked.append((title, text))
        return self.answer

    def _join(self):
        for name in ('_measure_job', '_checkup_job', '_idle_job'):
            job = getattr(self.panel, name, None)
            if job is not None:
                job.thread.join(timeout=5)

    def _wait(self, job):
        job.thread.join(timeout=5)
        self.assertFalse(job.thread.is_alive())
        deadline = time.monotonic() + 5
        while self.panel._measure_job is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.panel._measure_job)

    def _text(self):
        return self.panel.measure_text.get('1.0', 'end')

    def _buttons(self):
        return (self.panel.btn_measure_before, self.panel.btn_measure_after,
                self.panel.btn_checkup, self.panel.btn_idle)

    def test_block_starts_enabled_with_what_is_missing(self):
        self.assertEqual(self.panel.btn_measure_before.cget('text'), 'Medir ANTES (1 min)')
        self.assertEqual(self.panel.btn_measure_after.cget('text'), 'Medir DEPOIS (1 min)')
        for button in self._buttons():
            self.assertFalse(button.instate(['disabled']))
        self.assertEqual(str(self.panel.measure_text.cget('state')), 'disabled')
        text = self._text()
        self.assertIn(pm.MISSING_BEFORE, text)
        self.assertIn(pm.MISSING_AFTER, text)
        self.assertIn(pm.MEASURE_WARNING, text)

    def test_cancel_does_not_measure(self):
        self.answer = False
        with mock.patch.object(pm, 'read_measure', side_effect=_forbidden) as read:
            self.panel.measure_pc('antes')
        read.assert_not_called()
        self.assertEqual(self.asked[0][1], pm.MEASURE_CONFIRMATION)
        self.assertIsNone(self.panel._measure_job)
        self.assertFalse(self.panel.btn_measure_before.instate(['disabled']))
        self.assertIn('Nada foi lido', self.panel.note.get())
        self.assertFalse((self.tmp / pm.MEASURE_FILE).exists())

    def test_before_and_after_save_and_compare(self):
        release = threading.Event()
        started = threading.Event()

        def slow(*args, **kwargs):
            started.set()
            release.wait(5)
            return _measure()
        with mock.patch.object(pm, 'read_measure', side_effect=slow) as read:
            self.panel.measure_pc('antes')
            job = self.panel._measure_job
            self.assertIsNotNone(job)
            self.assertTrue(started.wait(5))
            self.root.update()
            for button in self._buttons():
                self.assertTrue(button.instate(['disabled']))
            self.assertEqual(self.panel.btn_measure_before.cget('text'), 'Medindo... (1 min)')
            # Enquanto mede: nem o check-up, nem o uso parado, nem outra medição começam.
            with mock.patch.object(ou.checkup_engine, 'read_checkup', side_effect=_forbidden), \
                    mock.patch.object(ou.checkup_engine, 'read_idle', side_effect=_forbidden):
                self.panel.security_checkup()
                self.panel.measure_idle()
            self.panel.measure_pc('depois')
            self.assertIs(self.panel._measure_job, job)
            self.assertEqual(len(self.asked), 1)
            release.set()
            self._wait(job)
        self.assertEqual(read.call_count, 1)
        for button in self._buttons():
            self.assertFalse(button.instate(['disabled']))
        self.assertEqual(self.panel.btn_measure_before.cget('text'), 'Medir ANTES (1 min)')
        self.assertIn(pm.MISSING_AFTER, self._text())
        with mock.patch.object(pm, 'read_measure', return_value=_measure(cpu=12, processes=180)):
            self.panel.measure_pc('depois')
            self._wait(self.panel._measure_job)
        text = self._text()
        self.assertIn('Uso do processador (média): 20% → 12% (8 pontos a menos)', text)
        self.assertIn('Processos abertos: 200 → 180 (20 a menos)', text)
        self.assertIn(pm.MEASURE_WARNING, text)
        saved = json.loads((self.tmp / pm.MEASURE_FILE).read_text(encoding='utf-8'))
        self.assertEqual([m['phase'] for m in saved['measures']], ['antes', 'depois'])
        self.assertNotIn(str(self.tmp), json.dumps(saved))

    def test_failure_shows_generic_message_and_saves_nothing(self):
        with mock.patch.object(pm, 'read_measure', side_effect=RuntimeError(r'C:\Users\Fulano\segredo')):
            self.panel.measure_pc('antes')
            self._wait(self.panel._measure_job)
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(self.shown[0][2], ou.MEASURE_FAILED_TEXT)
        self.assertNotIn('Fulano', ' '.join(map(str, self.shown[0])))
        self.assertFalse((self.tmp / pm.MEASURE_FILE).exists())
        for button in self._buttons():
            self.assertFalse(button.instate(['disabled']))

    def test_measure_buttons_off_while_checkup_or_idle_runs(self):
        release = threading.Event()

        def slow(*args, **kwargs):
            release.wait(5)
            return {'autostart': [], 'processes': [], 'unchecked': 0, 'errors': []}
        with mock.patch.object(ou.checkup_engine, 'read_checkup', side_effect=slow):
            self.panel.security_checkup()
            job = self.panel._checkup_job
            self.root.update()
            self.assertTrue(self.panel.btn_measure_before.instate(['disabled']))
            self.assertTrue(self.panel.btn_measure_after.instate(['disabled']))
            with mock.patch.object(pm, 'read_measure', side_effect=_forbidden) as read:
                self.panel.measure_pc('antes')
            read.assert_not_called()
            release.set()
            job.thread.join(timeout=5)
            deadline = time.monotonic() + 5
            while self.panel._checkup_job is not None and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
        self.assertFalse(self.panel.btn_measure_before.instate(['disabled']))
        window = self.panel._checkup_window
        if window is not None:
            window.destroy()
        release2 = threading.Event()

        def slow_idle(*args, **kwargs):
            release2.wait(5)
            return None
        with mock.patch.object(ou.checkup_engine, 'read_idle', side_effect=slow_idle):
            self.panel.measure_idle()
            job = self.panel._idle_job
            self.root.update()
            self.assertTrue(self.panel.btn_measure_after.instate(['disabled']))
            release2.set()
            job.thread.join(timeout=5)
            deadline = time.monotonic() + 5
            while self.panel._idle_job is not None and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
        self.assertFalse(self.panel.btn_measure_after.instate(['disabled']))
        window = self.panel._checkup_window
        if window is not None:
            window.destroy()

    def test_unreadable_history_is_shown_and_kept(self):
        path = self.tmp / pm.MEASURE_FILE
        path.write_text('{quebrado', encoding='utf-8')
        self.panel._render_measures()
        self.assertIn(ou.MEASURE_HISTORY_UNREADABLE, self._text())
        with mock.patch.object(pm, 'read_measure', return_value=_measure()):
            self.panel.measure_pc('antes')
            self._wait(self.panel._measure_job)
        self.assertEqual(path.read_text(encoding='utf-8'), '{quebrado')
        self.assertEqual(self.shown[0][2], ou.MEASURE_FAILED_TEXT)


if __name__ == '__main__':
    unittest.main()
