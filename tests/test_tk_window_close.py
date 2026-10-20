"""Tk integration checks: closing real dialogs must cancel their own callbacks.

Uses only Tk widgets and a mock restoration index; no real disks or backups.
"""
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from ui_timers import WindowTimers
from deep_discovery_ui import show_deep_discovery
from restore_ui import show_restore


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class WindowCloseLifecycleTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display indisponivel: {exc}')
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.root.busy = False
        self.errors = []
        self.root.tk.createcommand('bgerror', self.errors.append)

    @staticmethod
    def timer_capture(instances):
        def build(owner):
            timer = WindowTimers(owner)
            instances.append(timer)
            return timer
        return build

    def test_closing_discovery_dialog_cancels_idle_poll(self):
        self.root.dest = tk.StringVar(value='G:/backup')
        self.root.catalog_items = {}
        self.root.choices = {}
        self.root.cleanup_candidates = set()
        self.root.deep_scan_running = False
        self.root.deep_scan_report = dict(
            schema='pcro-discovery-v1', records=[], roots=[],
            errors=[], skipped=[], apps=[], volume_stats={})
        self.root._on_change = lambda: None
        self.root.navigate = lambda target: None
        self.root.refresh_catalog = lambda: None

        instances = []
        with (patch('deep_discovery_ui.local_drives', return_value=['C:/']),
              patch('deep_discovery_ui.WindowTimers',
                    side_effect=self.timer_capture(instances))):
            show_deep_discovery(self.root)

        self.assertEqual(len(instances), 1)
        timer = instances[0]
        window = next(w for w in self.root.winfo_children()
                      if isinstance(w, tk.Toplevel))
        self.assertTrue(timer.pending)
        window.destroy()
        self.assertTrue(timer.closed)
        self.assertFalse(timer.pending)
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_closing_restore_dialog_cancels_search_debounce(self):
        self.root.busy = False
        entries = {
            'C/Games/Other/save.dat': {
                'source': 'C:/Games/Other/save.dat', 'bytes': 99,
                'owners': [{'name': 'Other Game',
                            'category': 'Save do jogo',
                            'root': 'C:/Games/Other'}]}}
        instances = []
        with (patch('restore_ui.verified_entries', return_value=entries),
              patch('restore_ui.WindowTimers',
                    side_effect=self.timer_capture(instances))):
            show_restore(self.root, 'unused.json')
            deadline = time.monotonic() + 5
            while self.root.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertFalse(self.root.busy, 'indice de restauracao nao carregou')
        self.assertEqual(len(instances), 1)
        timer = instances[0]
        dialog = self.root.restore_dialog
        entry = next(w for w in descendants(dialog)
                     if isinstance(w, ttk.Entry))
        entry.insert(0, 'save')
        self.assertTrue(timer.pending)
        dialog.destroy()
        self.assertTrue(timer.closed)
        self.assertFalse(timer.pending)
        self.root.update()
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
