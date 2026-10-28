"""FIX-P2-09-08: the real protected copy refuses to run as administrator.

Only fake disk inventories and synthetic files inside TemporaryDirectory.
The elevation check is always a fake probe: no real ctypes/UAC call, no real
disk, command, PowerShell, WMI or registry. The window tests need Tk and a
display and are skipped without them.
"""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_disks_p2_09 import CountingCollector  # noqa: E402
from test_real_copy_flow_p2_09 import FORBIDDEN_POSITIVE, Base  # noqa: E402

import copy_authorization as ca  # noqa: E402
import copy_refusal as cr  # noqa: E402
import elevation_guard  # noqa: E402
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
WAIT = 10


def admin():
    return True


def not_admin():
    return False


def broken():
    raise OSError('falha simulada da conferência')


class Switch:
    """Probe whose answer the test changes between steps."""

    def __init__(self, value=False):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class AdminFlowTests(Base):
    def whole_tree(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))

    def assertAdminRefused(self, flow, state):
        self.assertEqual(state, rcf.RECUSADO)
        self.assertEqual(flow.state, rcf.RECUSADO)
        self.assertEqual(flow.message, rcf.MSG_ADMIN)
        self.assertIsNone(flow.preview)
        self.assertIsNone(flow._authorization)
        self.assertFalse(flow.executor_called)

    def test_elevated_refuses_before_reading_disks(self):
        collector = CountingCollector()
        before = self.whole_tree()
        with patch.object(executor, 'preview_real_execution') as preview, \
                patch.object(executor, 'run_real_copy') as run:
            flow = self.flow(collector, elevated_probe=admin)
            self.assertAdminRefused(flow, flow.request_disk_check())
            # Even forcing the next steps: still refused, nothing read.
            self.assertAdminRefused(flow, flow.confirm_disk_check(True))
            self.assertAdminRefused(flow, flow.confirm_copy(True))
            self.assertAdminRefused(flow, flow.run())
        preview.assert_not_called()
        run.assert_not_called()
        self.assertEqual(collector.calls, 0)
        self.assertEqual(self.whole_tree(), before)
        self.assertNothingWritten()

    def test_elevated_after_preview_refuses_before_authorizing(self):
        self.allow_temp_target()
        probe = Switch(False)
        collector = CountingCollector()
        flow = self.flow(collector, elevated_probe=probe)
        flow.request_disk_check()
        self.assertEqual(flow.confirm_disk_check(True), rcf.PREVIA)
        probe.value = True
        with patch.object(ca, 'authorize_copy') as authorize, \
                patch.object(rcf, 'authorize_copy') as authorize_in_flow:
            self.assertAdminRefused(flow, flow.confirm_copy(True))
        authorize.assert_not_called()
        authorize_in_flow.assert_not_called()
        self.assertEqual(collector.calls, 1)
        self.assertNothingWritten()

    def test_elevated_before_run_refuses_and_uses_the_token_up(self):
        self.allow_temp_target()
        probe = Switch(False)
        collector = CountingCollector()
        flow = self.flow(collector, elevated_probe=probe)
        flow.request_disk_check()
        flow.confirm_disk_check(True)
        self.assertEqual(flow.confirm_copy(True), rcf.CONFIRMADO)
        token = flow._authorization['token']
        probe.value = True
        with patch.object(executor, 'run_real_copy') as run:
            self.assertAdminRefused(flow, flow.run())
        run.assert_not_called()
        # FIX-P2-09-09: the executor never ran, so "nothing copied" holds.
        self.assertEqual(flow.message, rcf.MSG_ADMIN)
        self.assertFalse(flow.executor_called)
        self.assertNotIn(token, ca._ISSUED)
        self.assertEqual(collector.calls, 1)
        self.assertNothingWritten()
        # Destination folders stay empty; a missing one is never created.
        self.assertEqual(list(self.folders['target_T'].iterdir()), [])
        self.assertFalse((self.root / 'nao_existe').exists())

    def test_elevated_after_executor_ran_does_not_claim_nothing_copied(self):
        # FIX-P2-09-09 (R-19): after a real copy already ran, the admin
        # refusal must not say that nothing was copied.
        self.allow_temp_target()
        probe = Switch(False)
        flow = self.flow(CountingCollector(), elevated_probe=probe)
        flow.request_disk_check()
        flow.confirm_disk_check(True)
        flow.confirm_copy(True)
        self.assertEqual(flow.run(), rcf.CONCLUIDO)
        self.assertTrue(flow.executor_called)
        probe.value = True
        with patch.object(executor, 'run_real_copy') as run:
            self.assertEqual(flow.run(), rcf.RECUSADO)
        run.assert_not_called()
        self.assertEqual(flow.state, rcf.RECUSADO)
        self.assertEqual(flow.message, rcf.MSG_ADMIN_INCERTO)
        self.assertNotIn('Nada foi', flow.message)
        self.assertIsNone(flow._authorization)
        self.assertTrue(flow.executor_called)

    def test_not_elevated_flow_is_unchanged(self):
        self.allow_temp_target()
        probe = Switch(False)
        collector = CountingCollector()
        flow = self.flow(collector, elevated_probe=probe)
        self.assertEqual(flow.request_disk_check(), rcf.AVISO_CONSULTA)
        self.assertEqual(flow.confirm_disk_check(True), rcf.PREVIA)
        self.assertEqual(flow.confirm_copy(True), rcf.CONFIRMADO)
        self.assertEqual(flow.run(), rcf.CONCLUIDO)
        self.assertEqual(flow.result['status'], 'verificado')
        self.assertEqual(collector.calls, 3)
        self.assertEqual(probe.calls, 4)  # checked before each of the 4 steps
        for target in ('target_T', 'target_U'):
            self.assertEqual(len(list(self.folders[target].rglob('jogo.sav'))), 1)
        self.assertEqual(self.source_state(), self.state)

    def test_failing_probe_counts_as_not_elevated(self):
        # Documented behavior of elevation_guard.is_process_elevated: when the
        # check itself fails the answer is False (advisory, read only).
        self.assertFalse(elevation_guard.is_process_elevated(broken))
        self.assertFalse(rcf.process_elevated(broken))
        flow = self.flow(CountingCollector(), elevated_probe=broken)
        self.assertEqual(flow.request_disk_check(), rcf.AVISO_CONSULTA)

    def test_default_probe_is_the_real_guard(self):
        calls = []

        def fake(probe=None):
            calls.append(probe)
            return True

        flow = rcf.RealCopyFlow(self.plan, self.preview(), **self.kwargs())
        with patch.object(elevation_guard, 'is_process_elevated', side_effect=fake):
            self.assertEqual(flow.request_disk_check(), rcf.RECUSADO)
        self.assertEqual(calls, [None])
        self.assertEqual(flow.message, rcf.MSG_ADMIN)

    def test_refusal_is_typed(self):
        flow = self.flow(elevated_probe=admin)
        with self.assertRaises(cr.CopyRefusal) as caught:
            flow._require_not_elevated()
        self.assertEqual(caught.exception.kind, cr.KIND_ADMIN)
        self.assertIn(cr.KIND_ADMIN, cr.KINDS)
        self.assertIsInstance(caught.exception, ValueError)
        # The kind decides, not the text.
        self.assertEqual(rcf._reason(cr.CopyRefusal(cr.KIND_ADMIN, 'algo mudou')),
                         rcf.MSG_ADMIN)

    def test_message_is_plain_and_safe(self):
        text = rcf.MSG_ADMIN
        self.assertClean(text)
        self.assertIn('administrador', text)
        self.assertIn("sem usar 'Executar como administrador'", text)
        self.assertIn('Nada foi copiado nem gravado no destino.', text)
        for word in FORBIDDEN_POSITIVE + ('elevat', 'UAC', 'IsUserAnAdmin'):
            self.assertNotIn(word, text)

    def test_uncertain_message_is_plain_and_safe(self):
        # FIX-P2-09-09: same start as MSG_ADMIN, never claims "Nada foi".
        text = rcf.MSG_ADMIN_INCERTO
        self.assertClean(text)
        self.assertNotIn(os.path.expanduser('~'), text)
        self.assertNotIn('Nada foi', text)
        self.assertTrue(text.endswith('A cópia anterior pode ter ficado '
                                      'incompleta: trate-a como não verificada.'))
        start = rcf.MSG_ADMIN.split(' Nada foi')[0]
        self.assertTrue(text.startswith(start))
        for word in FORBIDDEN_POSITIVE + ('elevat', 'UAC', 'IsUserAnAdmin'):
            self.assertNotIn(word, text)


class AdminCodeShapeTests(unittest.TestCase):
    def test_flow_uses_the_existing_guard(self):
        code = (ROOT / 'real_copy_flow.py').read_text(encoding='utf-8')
        self.assertIn('elevation_guard.is_process_elevated(probe)', code)
        self.assertNotIn('IsUserAnAdmin', code)
        self.assertNotIn('ctypes', code)

    def test_window_uses_the_flow_check(self):
        ui = (ROOT / 'real_copy_ui.py').read_text(encoding='utf-8')
        self.assertIn('rcf.process_elevated(elevated_probe)', ui)
        self.assertIn('elevated_probe=elevated_probe', ui)
        self.assertNotIn('IsUserAnAdmin', ui)


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class AdminWindowTests(Base):
    def setUp(self):
        super().setUp()
        self.allow_temp_target()
        self.tk_root = tk.Tk()
        self.tk_root.withdraw()
        track_tk_root(self, self.tk_root)
        self.answers = []

    def ask(self, parent, title):
        return self.answers.pop(0) if self.answers else None

    def open(self, collector, probe):
        dlg = rcu.show_real_copy(self.tk_root, collector=collector, ask_folder=self.ask,
                                 volume_lookup=self.volume, usage=self.usage,
                                 elevated_probe=probe)
        self.addCleanup(self.finish, dlg)
        return dlg

    def finish(self, dlg):
        job = dlg.real_copy_state.get('job')
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        if job is not None:
            job.thread.join(WAIT)

    def click(self, dlg, name):
        dlg.real_copy_buttons[name].invoke()
        self.tk_root.update()

    def choose_all(self, dlg):
        self.answers = [str(self.folders['source_A']), str(self.folders['target_T'])]
        self.click(dlg, 'Adicionar origem')
        self.click(dlg, 'Adicionar destino')

    def enabled(self, dlg):
        return {name for name, button in dlg.real_copy_buttons.items()
                if not button.instate(['disabled'])}

    def labels(self, widget):
        found = []
        for child in widget.winfo_children():
            try:
                found.append(str(child.cget('text')))
            except tk.TclError:
                pass
            found += self.labels(child)
        return found

    def test_elevated_window_warns_and_keeps_read_disabled(self):
        collector = CountingCollector()
        dlg = self.open(collector, admin)
        self.assertIn(rcu.ADMIN_TEXT, self.labels(dlg))
        self.choose_all(dlg)
        self.assertNotIn('Ler discos', self.enabled(dlg))
        self.assertEqual(dlg.real_copy_status.get(), rcu.MSG_ADMIN_DESLIGADO)
        # Even calling the command directly does nothing.
        dlg.real_copy_buttons['Ler discos'].state(['!disabled'])
        self.click(dlg, 'Ler discos')
        time.sleep(0.1)
        self.tk_root.update()
        self.assertIsNone(dlg.real_copy_state['flow'])
        self.assertFalse(dlg.real_copy_state['busy'])
        self.assertEqual(collector.calls, 0)
        self.assertNothingWritten()

    def test_elevated_clear_choices_keeps_disabled_status(self):
        # FIX-P2-09-09 (R-18): "Limpar escolhas" keeps the admin status.
        collector = CountingCollector()
        dlg = self.open(collector, admin)
        self.choose_all(dlg)
        self.click(dlg, 'Limpar escolhas')
        self.assertEqual(dlg.real_copy_status.get(), rcu.MSG_ADMIN_DESLIGADO)
        self.assertNotIn('Ler discos', self.enabled(dlg))
        self.assertEqual(collector.calls, 0)
        self.assertNothingWritten()

    def test_not_elevated_window_has_no_warning(self):
        dlg = self.open(CountingCollector(), not_admin)
        self.assertNotIn(rcu.ADMIN_TEXT, self.labels(dlg))
        self.choose_all(dlg)
        self.assertIn('Ler discos', self.enabled(dlg))
        self.assertEqual(dlg.real_copy_status.get(), rcu.MSG_ESCOLHA)

    def test_window_texts_are_plain(self):
        for text in (rcu.ADMIN_TEXT, rcu.MSG_ADMIN_DESLIGADO):
            self.assertClean(text)
            for word in FORBIDDEN_POSITIVE + ('elevat', 'UAC'):
                self.assertNotIn(word, text)


if __name__ == '__main__':
    unittest.main()
