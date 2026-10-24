"""P2-09 slice 3b-2: real copy window and the flow's cancel/busy guards.

Only fake disk inventories and synthetic files inside TemporaryDirectory.
No real disk, command, PowerShell, WMI or registry is used. The window
tests need Tk and a display and are skipped without them; the code-shape
tests read the source with ast/text and run anywhere.
"""
import ast
import os
import re
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_disks_p2_09 import CountingCollector, fake_inventory  # noqa: E402
from test_real_copy_flow_p2_09 import FORBIDDEN_POSITIVE, Base, sha  # noqa: E402

import copy_authorization as ca  # noqa: E402
import multi_source_executor as executor  # noqa: E402
import real_copy_flow as rcf  # noqa: E402

try:
    import tkinter as tk
    import real_copy_ui as rcu
    from tk_helpers import track_tk_root
except ImportError:  # Python without Tk (e.g. Linux server): window tests skip.
    tk = rcu = track_tk_root = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))
ROOT = Path(__file__).resolve().parents[1]
LOCKS = ('copy' + '_authorized', 'physical_independence' + '_verified',
         'ready_for' + '_format', 'installation' + '_authorized',
         'deletions' + '_authorized')
WAIT = 10


class GateCollector(CountingCollector):
    """Collector that blocks on chosen calls until ``release()``."""

    def __init__(self, *inventories, block_on=(1,)):
        super().__init__(*inventories)
        self.block_on = set(block_on)
        self.entered = threading.Event()
        self.gate = threading.Event()

    def __call__(self):
        number = self.calls + 1
        if number in self.block_on:
            self.entered.set()
            self.gate.wait(WAIT)
        return super().__call__()

    def release(self):
        self.gate.set()


def in_thread(func, *args, **kwargs):
    box = {}

    def target():
        box['value'] = func(*args, **kwargs)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


class FlowGuardTests(Base):
    def confirmed(self, collector=None):
        self.allow_temp_target()
        flow = self.flow(collector)
        flow.request_disk_check()
        self.assertEqual(flow.confirm_disk_check(True), rcf.PREVIA)
        self.assertEqual(flow.confirm_copy(True), rcf.CONFIRMADO)
        return flow

    def test_run_hands_its_own_event_to_the_executor(self):
        flow = self.confirmed()
        self.assertIsInstance(flow.cancel_event, threading.Event)
        seen = {}

        def fake(*args, **kwargs):
            seen.update(kwargs)
            return {'status': 'verificado', 'destinations': []}

        with patch.object(executor, 'run_real_copy', side_effect=fake), \
                patch.object(executor, 'format_report_pt', return_value='ok'):
            self.assertEqual(flow.run(), rcf.CONCLUIDO)
        self.assertIs(seen['cancelled'], flow.cancel_event)

    def test_second_call_during_disk_check_is_refused(self):
        self.allow_temp_target()
        collector = GateCollector()
        flow = self.flow(collector)
        flow.request_disk_check()
        thread, box = in_thread(flow.confirm_disk_check, True)
        self.assertTrue(collector.entered.wait(WAIT))
        self.assertTrue(flow.busy)
        for name, call in (('confirm_disk_check', lambda: flow.confirm_disk_check(True)),
                           ('request_disk_check', flow.request_disk_check),
                           ('confirm_copy', lambda: flow.confirm_copy(True)),
                           ('run', flow.run), ('reset', flow.reset)):
            with self.subTest(name):
                self.assertEqual(call(), rcf.OCUPADO)
                self.assertEqual(flow.state, rcf.AVISO_CONSULTA)
                self.assertEqual(collector.calls, 0)
        collector.release()
        thread.join(WAIT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box['value'], rcf.PREVIA)
        self.assertEqual(collector.calls, 1)
        self.assertFalse(flow.busy)
        self.assertNothingWritten()

    def test_second_run_during_copy_is_refused(self):
        flow = self.confirmed()
        started, gate, calls = threading.Event(), threading.Event(), []

        def slow(*args, **kwargs):
            calls.append(kwargs['authorization'])
            started.set()
            gate.wait(WAIT)
            return {'status': 'verificado', 'destinations': []}

        with patch.object(executor, 'run_real_copy', side_effect=slow), \
                patch.object(executor, 'format_report_pt', return_value='ok'):
            thread, box = in_thread(flow.run)
            self.assertTrue(started.wait(WAIT))
            self.assertEqual(flow.run(), rcf.OCUPADO)
            self.assertEqual(flow.confirm_copy(True), rcf.OCUPADO)
            self.assertEqual(flow.state, rcf.CONFIRMADO)
            gate.set()
            thread.join(WAIT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box['value'], rcf.CONCLUIDO)
        self.assertEqual(len(calls), 1)

    def test_cancel_during_copy_only_sets_the_event(self):
        # Third disk read happens inside run() before destination 2: cancel there.
        collector = GateCollector(block_on=(3,))
        flow = self.confirmed(collector)
        token = flow._authorization['token']
        thread, box = in_thread(flow.run)
        self.assertTrue(collector.entered.wait(WAIT))
        self.assertEqual(flow.cancel(), rcf.OCUPADO)
        self.assertTrue(flow.cancel_event.is_set())
        self.assertEqual(flow.state, rcf.CONFIRMADO)
        collector.release()
        thread.join(WAIT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box['value'], rcf.INCOMPLETO)
        self.assertEqual(flow.state, rcf.INCOMPLETO)
        self.assertEqual(flow.message, rcf.MSG_INCOMPLETO)
        self.assertNotEqual(flow.result['status'], 'verificado')
        self.assertNotIn(token, ca._ISSUED)
        self.assertClean(flow.report)
        # Destination 1 ended verified; destination 2 began with the Event set
        # and was not verified. The sources were only read.
        rows = flow.result['destinations']
        self.assertEqual(rows[0]['status'], 'verificado')
        self.assertNotEqual(rows[1]['status'], 'verificado')
        self.assertEqual(list(self.folders['target_U'].rglob('jogo.sav')), [])
        self.assertEqual(self.source_state(), self.state)

    def test_cancel_during_disk_check_drops_the_preview(self):
        self.allow_temp_target()
        collector = GateCollector()
        flow = self.flow(collector)
        flow.request_disk_check()
        thread, box = in_thread(flow.confirm_disk_check, True)
        self.assertTrue(collector.entered.wait(WAIT))
        self.assertEqual(flow.cancel(), rcf.OCUPADO)
        collector.release()
        thread.join(WAIT)
        self.assertEqual(box['value'], rcf.INICIO)
        self.assertIsNone(flow.preview)
        self.assertEqual(flow.message, rcf.CANCELADO)
        # A new attempt starts clean (the Event is cleared).
        self.assertEqual(flow.request_disk_check(), rcf.AVISO_CONSULTA)
        self.assertFalse(flow.cancel_event.is_set())
        self.assertNothingWritten()

    def test_cancel_when_idle_resets_and_allows_a_new_attempt(self):
        flow = self.confirmed()
        token = flow._authorization['token']
        self.assertEqual(flow.cancel(), rcf.INICIO)
        self.assertEqual(flow.message, rcf.CANCELADO)
        self.assertNotIn(token, ca._ISSUED)
        self.assertFalse(flow.cancel_event.is_set())
        self.assertEqual(flow.request_disk_check(), rcf.AVISO_CONSULTA)
        self.assertNothingWritten()

    def test_close_uses_the_token_up_and_refuses_later_steps(self):
        collector = CountingCollector()
        flow = self.confirmed(collector)
        token = flow._authorization['token']
        self.assertEqual(flow.close(), rcf.INICIO)
        self.assertNotIn(token, ca._ISSUED)
        self.assertTrue(flow.cancel_event.is_set())
        flow.request_disk_check()
        self.assertTrue(flow.cancel_event.is_set())
        for call in (flow.request_disk_check, lambda: flow.confirm_disk_check(True),
                     lambda: flow.confirm_copy(True), flow.run):
            self.assertEqual(call(), rcf.INICIO)
            self.assertEqual(flow.message, rcf.CANCELADO)
        self.assertEqual(collector.calls, 1)
        self.assertNothingWritten()

    def test_close_during_copy_stops_it(self):
        collector = GateCollector(block_on=(2,))
        flow = self.confirmed(collector)
        token = flow._authorization['token']
        thread, box = in_thread(flow.run)
        self.assertTrue(collector.entered.wait(WAIT))
        self.assertEqual(flow.close(), rcf.OCUPADO)
        collector.release()
        thread.join(WAIT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box['value'], rcf.INCOMPLETO)
        self.assertNotIn(token, ca._ISSUED)
        self.assertNothingWritten()


class CodeShapeTests(unittest.TestCase):
    def setUp(self):
        self.ui = (ROOT / 'real_copy_ui.py').read_text(encoding='utf-8')
        self.tree = ast.parse(self.ui)
        self.app = (ROOT / 'app.py').read_text(encoding='utf-8')

    def calls(self, tree=None):
        return [node for node in ast.walk(tree or self.tree) if isinstance(node, ast.Call)]

    def test_window_uses_only_the_flow(self):
        for word in ('multi_source_executor', 'copy_authorization', 'physical_independence',
                     'physical_disk_check', 'authorize_copy', 'run_real_copy',
                     'preview_real_execution', 'subprocess', 'os.system', 'powershell',
                     'PowerShell'):
            with self.subTest(word=word):
                self.assertNotIn(word, self.ui)
        modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertIn('real_copy_flow', modules)
        self.assertLessEqual(modules, {
            '__future__', 'shutil', 'tkinter', 'pathlib', 'diagnostics', 'real_copy_flow',
            'multi_source_plan', 'multi_source_targets', 'restore_jobs', 'ui_timers',
            'volume_paths'})

    def test_no_lock_names_and_no_deletes(self):
        for word in LOCKS + ('unlink', 'rmtree', 'remove(', 'rmdir', 'os.replace',
                             'rename', 'open('):
            with self.subTest(word=word):
                self.assertNotIn(word, self.ui)

    def test_errors_are_never_shown(self):
        # R-07: the window never binds an exception, so it cannot show str(error).
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ExceptHandler):
                self.assertIsNone(node.name)
        self.assertIsNone(re.search(r'str\((err|exc|error|value)\)', self.ui))

    def test_disk_query_only_through_confirm_disk_check_true(self):
        for call in self.calls():
            func = call.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, 'attr', None)
            self.assertNotIn(name, ('collector', 'disk_collector', 'disk_inventory'))
            if name == 'confirm_disk_check':
                self.assertEqual(len(call.args), 1)
                self.assertFalse(call.keywords)
                self.assertIsInstance(call.args[0], ast.Constant)
                self.assertIn(call.args[0].value, (True, False))
        trues = [c for c in self.calls() if getattr(c.func, 'attr', None) == 'confirm_disk_check'
                 and c.args[0].value is True]
        self.assertEqual(len(trues), 1)
        # The default collector is only referenced, never called here.
        self.assertIn('collector or diagnostics.disk_inventory', self.ui)

    def test_after_only_through_window_timers(self):
        for call in self.calls():
            if getattr(call.func, 'attr', None) in ('after', 'after_idle'):
                self.assertEqual(ast.unparse(call.func.value), 'timers')

    def test_texts_are_clean(self):
        texts = [value for name, value in vars(rcu).items()
                 if isinstance(value, str) and name.isupper()] if rcu else []
        constants = [node.value for node in ast.walk(self.tree)
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        for text in texts + constants:
            for word in FORBIDDEN_POSITIVE:
                self.assertNotIn(word, text)

    def test_app_imports_the_window_late_and_only_it(self):
        tree = ast.parse(self.app)
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                top.add(node.module)
        self.assertNotIn('real_copy_ui', top)
        late = [node for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == 'real_copy_ui']
        self.assertEqual(len(late), 1)
        self.assertEqual([alias.name for alias in late[0].names], ['show_real_copy'])
        for word in ('real_copy_flow', 'multi_source_executor', 'copy_authorization'):
            self.assertNotIn(word, self.app)
        self.assertIn("self._nav_action('⇉', 'Cópia protegida para outro disco'", self.app)
        self.assertNotIn("_nav_entry('real_copy'", self.app)


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class WindowTests(Base):
    def setUp(self):
        super().setUp()
        self.allow_temp_target()
        self.tk_root = tk.Tk()
        self.tk_root.withdraw()
        track_tk_root(self, self.tk_root)
        self.answers = []

    def ask(self, parent, title):
        return self.answers.pop(0) if self.answers else None

    def open(self, collector):
        dlg = rcu.show_real_copy(self.tk_root, collector=collector, ask_folder=self.ask,
                                 volume_lookup=self.volume, usage=self.usage)
        self.addCleanup(self.finish, dlg)
        return dlg

    def finish(self, dlg):
        job = dlg.real_copy_state.get('job')
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        if job is not None:
            job.thread.join(WAIT)  # R-06: worker ended before the temp folder goes

    def pump(self, dlg):
        until = time.monotonic() + WAIT
        while dlg.real_copy_state['busy'] and time.monotonic() < until:
            self.tk_root.update()
            time.sleep(0.02)
        self.tk_root.update()
        self.assertFalse(dlg.real_copy_state['busy'])

    def click(self, dlg, name):
        dlg.real_copy_buttons[name].invoke()
        self.tk_root.update()

    def choose_all(self, dlg):
        self.answers = [str(self.folders['source_A']), str(self.folders['source_B'])]
        self.click(dlg, 'Adicionar origem')
        self.click(dlg, 'Adicionar origem')
        self.answers = [str(self.folders['target_T']), str(self.folders['target_U'])]
        self.click(dlg, 'Adicionar destino')
        self.click(dlg, 'Adicionar destino')

    def visible(self, dlg):
        return '\n'.join((dlg.real_copy_status.get(), dlg.real_copy_choices.get(),
                          dlg.real_copy_text()))

    def enabled(self, dlg):
        return {name for name, button in dlg.real_copy_buttons.items()
                if not button.instate(['disabled'])}

    def test_full_flow_copies_and_verifies(self):
        collector = CountingCollector()
        dlg = self.open(collector)
        self.assertNotIn('Ler discos', self.enabled(dlg))
        self.choose_all(dlg)
        self.click(dlg, 'Ler discos')
        self.pump(dlg)
        flow = dlg.real_copy_state['flow']
        self.assertEqual(flow.state, rcf.AVISO_CONSULTA)
        self.assertEqual(dlg.real_copy_status.get(), rcf.AVISO_CONSULTA_TEXTO)
        self.assertEqual(collector.calls, 0)
        self.assertLessEqual({'Sim, pode ler', 'Não'}, self.enabled(dlg))
        self.assertNotIn('Copiar agora', self.enabled(dlg))
        self.click(dlg, 'Sim, pode ler')
        self.pump(dlg)
        self.assertEqual(flow.state, rcf.PREVIA)
        self.assertEqual(collector.calls, 1)
        self.assertIn('Destino 1 (unidade T:)', dlg.real_copy_text())
        self.assertNotIn('Copiar agora', self.enabled(dlg))
        self.click(dlg, 'Confirmo esta cópia')
        self.assertEqual(flow.state, rcf.CONFIRMADO)
        self.assertIn('Copiar agora', self.enabled(dlg))
        self.click(dlg, 'Copiar agora')
        self.pump(dlg)
        self.assertEqual(flow.state, rcf.CONCLUIDO)
        self.assertIn('Todas as cópias foram feitas e conferidas.', dlg.real_copy_text())
        self.assertClean(self.visible(dlg))
        for target in ('target_T', 'target_U'):
            copied = list(self.folders[target].rglob('documento.txt'))
            self.assertEqual(len(copied), 1)
            self.assertEqual(sha(copied[0]), sha(self.first))
        self.assertEqual(self.source_state(), self.state)

    def test_no_reads_the_disks_and_nothing_is_written(self):
        collector = CountingCollector()
        dlg = self.open(collector)
        self.choose_all(dlg)
        self.click(dlg, 'Ler discos')
        self.pump(dlg)
        self.click(dlg, 'Não')
        self.assertEqual(dlg.real_copy_state['flow'].state, rcf.INICIO)
        self.assertEqual(dlg.real_copy_status.get(), rcu.MSG_NAO_LER)
        self.assertEqual(collector.calls, 0)
        self.assertNothingWritten()

    def test_same_disk_is_refused_with_short_reason(self):
        same = fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3})
        dlg = self.open(CountingCollector(same))
        self.choose_all(dlg)
        self.click(dlg, 'Ler discos')
        self.pump(dlg)
        self.click(dlg, 'Sim, pode ler')
        self.pump(dlg)
        self.click(dlg, 'Confirmo esta cópia')
        self.assertNotIn('Copiar agora', self.enabled(dlg))
        self.assertClean(self.visible(dlg))
        for word in FORBIDDEN_POSITIVE:
            self.assertNotIn(word, self.visible(dlg))
        self.assertNothingWritten()

    def test_one_window_only(self):
        dlg = self.open(CountingCollector())
        again = rcu.show_real_copy(self.tk_root, collector=CountingCollector())
        self.assertIs(again, dlg)
        dlg.destroy()
        self.tk_root.update()
        self.assertIsNone(self.tk_root.real_copy_dialog)

    def test_closing_during_copy_stops_it_with_no_pending_after(self):
        collector = GateCollector(block_on=(2,))
        dlg = self.open(collector)
        self.choose_all(dlg)
        self.click(dlg, 'Ler discos')
        self.pump(dlg)
        self.click(dlg, 'Sim, pode ler')
        self.pump(dlg)
        self.click(dlg, 'Confirmo esta cópia')
        flow = dlg.real_copy_state['flow']
        token = flow._authorization['token']
        self.click(dlg, 'Copiar agora')
        self.assertTrue(collector.entered.wait(WAIT))
        job = dlg.real_copy_state['job']
        timers = dlg.real_copy_timers
        dlg.destroy()
        self.assertTrue(timers.closed)
        self.assertEqual(timers.pending, set())
        self.assertTrue(flow.cancel_event.is_set())
        self.assertTrue(job.cancelled.is_set())
        collector.release()
        job.thread.join(WAIT)
        self.assertFalse(job.thread.is_alive())
        self.tk_root.update()
        self.assertEqual(flow.state, rcf.INCOMPLETO)
        self.assertNotIn(token, ca._ISSUED)
        self.assertNothingWritten()

    def test_closing_before_copy_uses_the_token_up(self):
        dlg = self.open(CountingCollector())
        self.choose_all(dlg)
        self.click(dlg, 'Ler discos')
        self.pump(dlg)
        self.click(dlg, 'Sim, pode ler')
        self.pump(dlg)
        self.click(dlg, 'Confirmo esta cópia')
        flow = dlg.real_copy_state['flow']
        token = flow._authorization['token']
        dlg.destroy()
        self.tk_root.update()
        self.assertNotIn(token, ca._ISSUED)
        self.assertEqual(flow.run(), rcf.INICIO)
        self.assertNothingWritten()


if __name__ == '__main__':
    unittest.main()
