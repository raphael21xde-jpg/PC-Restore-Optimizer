"""End-to-end synthetic tests; 2 GiB is opt-in to avoid repeated heavy writes."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from autotestes_escala import (run_gigabyte_autotest, run_abrupt_exit_autotest,
                               run_responsiveness_autotest, preflight, launch, GIB)
from tk_helpers import track_tk_root


class TestEscala(unittest.TestCase):
    def common(self, report):
        self.assertEqual(report['status'], 'aprovado')
        self.assertTrue(report['temporary_data_cleaned'])
        self.assertTrue(report['backup_sha256_verified'])
        self.assertTrue(report['restore_sha256_verified'])
        self.assertTrue(report['original_fixture_preserved'])
        for key in ('real_user_backups_accessed', 'physical_independence_verified',
                    'ready_for_format', 'installation_authorized'):
            self.assertFalse(report[key])

    @unittest.skipUnless(os.environ.get('PCRO_RUN_2GIB') == '1', '2 GiB: dedicated opt-in CI step')
    def test_35_real_2gib_transfer_and_process_peak(self):
        report = run_gigabyte_autotest()
        self.common(report)
        self.assertEqual(report['fixture_bytes'], 2 * GIB)
        self.assertGreater(report['process_peak_rss_bytes'], 0)
        self.assertLessEqual(report['process_peak_rss_bytes'], report['peak_rss_limit_bytes'])

    def test_36_abrupt_exit_and_restart_both_directions(self):
        report = run_abrupt_exit_autotest()
        self.common(report)
        self.assertEqual(report['child_exit_code'], 86)
        for key in ('backup_process_abruptly_exited', 'restore_process_abruptly_exited',
                    'partial_manifest_rejected', 'backup_resumed_in_new_process',
                    'restore_resumed_in_new_process'):
            self.assertTrue(report[key])
        self.assertGreater(report['abandoned_backup_fragments'], 0)
        self.assertGreater(report['abandoned_restore_fragments'], 0)

    def test_cancel_before_start(self):
        cancelled = threading.Event()
        cancelled.set()
        for runner in (run_gigabyte_autotest, run_abrupt_exit_autotest, run_responsiveness_autotest):
            with self.subTest(runner=runner.__name__), self.assertRaises(InterruptedError):
                runner(cancelled=cancelled)

    def test_insufficient_space_blocks_before_generation(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('autotestes_escala.shutil.disk_usage') as disk:
                disk.return_value.free = GIB
                with self.assertRaisesRegex(OSError, 'Teste não iniciado'):
                    preflight(root, 2 * GIB)
                self.assertEqual(list(Path(root).iterdir()), [])

    def test_wrong_child_exit_never_approves(self):
        with patch('autotestes_escala.launch', return_value=0):
            with self.assertRaisesRegex(AssertionError, 'Saída abrupta'):
                run_abrupt_exit_autotest()

    def test_gui_probe_required(self):
        with self.assertRaises(ValueError):
            run_responsiveness_autotest()

    def test_child_rejects_unowned_tree(self):
        import subprocess
        import sys
        from autotestes_escala import __file__ as script
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, script, '--child', root, 'fake', 'large'],
                                    capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_cancel_stops_only_spawned_child_and_waits(self):
        # Exercise cancellation while the child runs, not only before launch.
        import subprocess
        import sys
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        event = threading.Event()
        try:
            with tempfile.TemporaryDirectory() as name:
                with patch('autotestes_escala.subprocess.Popen', return_value=process):
                    timer = threading.Timer(.2, event.set)
                    timer.start()
                    with self.assertRaises(InterruptedError):
                        launch(Path(name), 'unused', 'large', cancelled=event)
                    timer.join()
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


class TestTkResponsiveness(unittest.TestCase):
    def test_37_real_tk_button_heartbeat_cancel_and_export(self):
        import tkinter as tk
        from tkinter import ttk
        from selective_backup_ui import show_selective_backup
        try:
            app = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get('PCRO_REQUIRE_TK') == '1':
                self.fail(f'Tk obrigatório nesta etapa: {exc}')
            self.skipTest(f'No display: {exc}')
        app.withdraw()
        track_tk_root(self, app)
        window = None
        def widgets(parent):
            for widget in parent.winfo_children():
                yield widget
                yield from widgets(widget)
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'report.json'
                with patch('selective_backup_ui.messagebox.showerror') as errors, \
                     patch('selective_backup_ui.messagebox.showinfo'), \
                     patch('selective_backup_ui.filedialog.asksaveasfilename', return_value=str(output)):
                    window = show_selective_backup(app, {'requires_verified_backup': []})
                    buttons = [w for w in widgets(window) if isinstance(w, ttk.Button)]
                    start = next(w for w in buttons if '17. Autoteste #37:' in str(w.cget('text')))
                    export = next(w for w in buttons if str(w.cget('text')) == 'Exportar relatório')
                    start.invoke()
                    deadline = time.monotonic() + 45
                    # A second scheduled GUI command must also run during the worker's I/O.
                    dispatched = []
                    app.after(400, lambda: dispatched.append(True))
                    while start.instate(['disabled']) and time.monotonic() < deadline:
                        app.update()
                        time.sleep(.01)
                    self.assertFalse(start.instate(['disabled']), 'Worker did not finish')
                    self.assertTrue(dispatched)
                    errors.assert_not_called()
                    export.invoke()
                    report = json.loads(output.read_text())
                    self.assertEqual(report['status'], 'aprovado')
                    self.assertTrue(report['tk_cancel_button_invoked'])
                    self.assertTrue(report['gui_cancel_observed'])
                    self.assertTrue(report['tk_event_loop_passed'])
                    self.assertGreaterEqual(report['tk_event_loop_ticks'], 8)
                    self.assertLessEqual(report['maximum_tk_gap_seconds'], 1.0)
                    self.assertTrue(report['temporary_data_cleaned'])
                    self.assertTrue(report['restore_sha256_verified'])
        finally:
            if window is not None:
                window.destroy()
            app.destroy()


if __name__ == '__main__':
    unittest.main()
