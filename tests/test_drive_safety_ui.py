"""Focused Tk safety smoke tests; never query real disks or run PowerShell."""
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from drive_safety_ui import show_drive_safety_dialog
from tk_helpers import track_tk_root


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


def fake_summary():
    return {
        'status': 'requires_review',
        'source_volumes': [
            {'letter': 'C:', 'logical_disk_numbers': [0],
             'extent_status': 'observed_logical_only'}],
        'destinations': [{
            'letter': 'G:', 'logical_disk_numbers': [2],
            'status': 'requires_review', 'blockers': [],
            'issues': ['Discos lógicos distintos não comprovam independência física.'],
        }],
        'copy_authorized': False,
        'physical_independence_verified': False,
        'ready_for_format': False,
        'installation_authorized': False,
    }


class DriveSafetyUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk indisponível: {exc}')
        self.root.withdraw()
        track_tk_root(self, self.root)

    def open_dialog(self):
        dialog = show_drive_safety_dialog(
            self.root, available_letters=('C', 'D', 'G'))
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        controls = {w.cget('text'): w for w in children(dialog)
                    if isinstance(w, ttk.Button)}
        entries = [w for w in children(dialog) if isinstance(w, ttk.Entry)]
        tables = [w for w in children(dialog) if isinstance(w, ttk.Treeview)]
        texts = [w for w in children(dialog) if isinstance(w, tk.Text)]
        self.assertEqual(len(entries), 2)
        self.assertEqual(len(tables), 1)
        self.assertEqual(len(texts), 1)
        return dialog, controls, entries, tables[0], texts[0]

    def wait_until(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Janela de diagnóstico não concluiu a operação.')

    def configure(self, entries, source='C:', target='G:'):
        for widget, value in zip(entries, (source, target)):
            widget.delete(0, 'end')
            widget.insert(0, value)

    def test_callable_tk_busy_attribute_does_not_block_opening(self):
        # Tk widgets may have a busy method, not an active-operation flag.
        self.root.busy = lambda: True
        with patch('drive_safety_ui.messagebox.showinfo') as notice:
            dialog = show_drive_safety_dialog(
                self.root, available_letters=('C', 'D', 'G'))
        self.assertIsInstance(dialog, tk.Toplevel)
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        notice.assert_not_called()

    def test_explicit_app_busy_true_blocks_dialog_without_collection(self):
        self.root.busy = True
        with (patch('drive_safety_ui.messagebox.showinfo') as notice,
              patch('drive_safety_ui.inspect_fresh_drive_safety') as inspect):
            dialog = show_drive_safety_dialog(
                self.root, available_letters=('C', 'D', 'G'))
        self.assertIsNone(dialog)
        notice.assert_called_once()
        inspect.assert_not_called()

    def test_opening_window_never_runs_disk_inventory(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as inspect:
            dialog, controls, entries, table, text = self.open_dialog()
            self.root.update()
            inspect.assert_not_called()
            self.assertEqual(table.get_children(''), ())
            self.assertIn('Nenhuma unidade foi aprovada',
                          text.get('1.0', 'end'))
            self.assertEqual(entries[0].get(), '')
            self.assertEqual(entries[1].get(), '')

    def test_operator_must_choose_distinct_valid_letters_before_collection(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as inspect:
            _, controls, entries, table, text = self.open_dialog()
            self.configure(entries, source='C:,C:', target='G:')
            controls['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.configure(entries, source='C:', target='C:')
            controls['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.configure(entries, source='C:/Windows', target='G:')
            controls['Conferir discos (SOMENTE LEITURA)'].invoke()
            inspect.assert_not_called()
            self.assertEqual(table.get_children(''), ())

    def test_explicit_click_collects_once_and_shows_only_safe_summary(self):
        calls = []
        def fake_inspector(sources, targets):
            calls.append((sources, targets))
            return fake_summary()
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   side_effect=fake_inspector):
            _, controls, entries, table, result = self.open_dialog()
            self.configure(entries, source='c:', target='g:')
            controls['Conferir discos (SOMENTE LEITURA)'].invoke()
            # Wait for the final summary, not only the table rows.
            self.wait_until(lambda: len(table.get_children('')) == 2 and
                            'NÃO AUTORIZADOS' in result.get('1.0', 'end'))
        self.assertEqual(calls, [(['C'], ['G'])])
        rows = [table.item(x, 'text') for x in table.get_children('')]
        self.assertEqual(rows, ['C:', 'G:'])
        displayed = result.get('1.0', 'end')
        self.assertIn('NÃO AUTORIZADOS', displayed)
        self.assertIn('independência física', displayed)
        self.assertNotIn('SerialNumber', displayed)

    def test_failure_does_not_show_raw_private_diagnostic_exception(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   side_effect=RuntimeError('PRIVATE-DEVICE-SERIAL-12345')):
            _, controls, entries, table, result = self.open_dialog()
            self.configure(entries)
            controls['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.wait_until(
                lambda: ('Não foi possível completar a leitura'
                         in result.get('1.0', 'end')))
        self.assertNotIn('PRIVATE-DEVICE-SERIAL',
                         result.get('1.0', 'end'))
        self.assertEqual(table.get_children(''), ())

    def test_close_during_background_query_waits_for_completion(self):
        started = threading.Event()
        release = threading.Event()
        def fake_inspector(sources, targets):
            started.set()
            if not release.wait(timeout=3):
                raise RuntimeError('timeout')
            return fake_summary()
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   side_effect=fake_inspector):
            dialog, controls, entries, table, result = self.open_dialog()
            self.configure(entries)
            controls['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.assertTrue(started.wait(2))
            controls['Fechar'].invoke()
            self.assertTrue(dialog.winfo_exists())
            release.set()
            self.wait_until(lambda: not dialog.winfo_exists())


if __name__ == '__main__':
    unittest.main()
