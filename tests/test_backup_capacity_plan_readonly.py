"""Stage 41: capacity estimates from user input, never a real copy.

All collections are synthetic and the UI inspector is replaced by a mock.
"""
from __future__ import annotations

from decimal import Decimal
import gc
import threading
import json
import tkinter as tk
from tkinter import ttk
import time
import unittest
from unittest.mock import patch

from backup_capacity_input import GIB, parse_estimated_backup_gib
from drive_safety_report import inspect_fresh_drive_safety
from drive_safety_export import safe_drive_report_json
from drive_safety_ui import show_drive_safety_dialog
from tk_helpers import close_tk_root


def fixture(free=100 * GIB):
    return {
        'disks': [
            {'Number': 4, 'BusType': 'NVMe', 'IsBoot': True,
             'SerialNumber': 'PRIVATE-HARDWARE-SERIAL'},
            {'Number': 5, 'BusType': 'SATA'},
        ],
        'partitions': [
            {'DriveLetter': 'Q', 'DiskNumber': 4, 'IsBoot': True},
            {'DriveLetter': 'R', 'DiskNumber': 5},
        ],
        'volumes': [
            {'DriveLetter': 'Q', 'SizeRemaining': 5 * GIB},
            {'DriveLetter': 'R', 'SizeRemaining': free},
        ],
        'extent_mapping': {'volumes': [
            {'letters': ['Q'], 'disk_numbers': [4], 'status': 'logical_disk_reported'},
            {'letters': ['R'], 'disk_numbers': [5], 'status': 'logical_disk_reported'},
        ]},
        'spaces_membership': {},
    }


def inspect(*, estimated=None, free=100 * GIB):
    report = fixture(free=free)
    return inspect_fresh_drive_safety(
        ['Q'], ['R'], collector=lambda: report,
        expected_backup_bytes=estimated)


class CapacityInputTests(unittest.TestCase):
    def test_empty_input_means_not_evaluated_not_zero_bytes(self):
        self.assertIsNone(parse_estimated_backup_gib(''))
        self.assertIsNone(parse_estimated_backup_gib('   '))
        result = inspect()
        dest = result['destinations'][0]
        self.assertIsNone(dest['expected_backup_bytes'])
        self.assertEqual(dest['capacity_status'], 'not_evaluated')

    def test_brazilian_comma_and_dot_in_gib(self):
        for text in ('1,5', '1.5'):
            self.assertEqual(parse_estimated_backup_gib(text), 3 * GIB // 2)
        self.assertEqual(parse_estimated_backup_gib('120'), 120 * GIB)

    def test_small_size_rounds_up_to_whole_byte(self):
        result = parse_estimated_backup_gib('0,001')
        self.assertEqual(result, 1073742)
        self.assertGreater(result, 0)

    def test_malformed_or_unsafe_values_rejected(self):
        for bad in ('0', '-1', 'NaN', 'Infinity', '1e5',
                    '1,2,3', '1.1234', '1;Remove-Item',
                    '99999999999999', '1\x00', 'C:', '1/2'):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                parse_estimated_backup_gib(bad)
        with self.assertRaises(ValueError):
            parse_estimated_backup_gib(1.5)

    def test_full_estimated_capacity_does_not_approve_copy(self):
        result = inspect(estimated=10 * GIB)
        dest = result['destinations'][0]
        self.assertEqual(dest['capacity_status'], 'reported_sufficient')
        self.assertEqual(dest['free_bytes_reported'], 100 * GIB)
        self.assertEqual(dest['expected_backup_bytes'], 10 * GIB)
        self.assertIn('capacity_reported_only', dest['findings'])
        self.assertEqual(dest['status'], 'requires_review')
        for key in ('copy_authorized', 'physical_independence_verified',
                    'ready_for_format', 'installation_authorized'):
            self.assertIs(result[key], False)

    def test_insufficient_capacity_is_blocked(self):
        result = inspect(estimated=101 * GIB)
        dest = result['destinations'][0]
        self.assertEqual(dest['capacity_status'], 'insufficient')
        self.assertIn('capacity_insufficient', dest['findings'])
        self.assertEqual(dest['status'], 'blocked')

    def test_unknown_free_space_is_blocked(self):
        result = inspect(estimated=10 * GIB, free=None)
        dest = result['destinations'][0]
        self.assertEqual(dest['capacity_status'], 'unknown')
        self.assertIsNone(dest['free_bytes_reported'])
        self.assertIn('capacity_unknown', dest['findings'])
        self.assertEqual(dest['status'], 'blocked')

    def test_clipboard_only_exports_safe_bounded_numbers(self):
        result = inspect(estimated=10 * GIB)
        parsed = json.loads(safe_drive_report_json(result))
        target = parsed['destinations'][0]
        self.assertEqual(target['expected_backup_bytes'], 10 * GIB)
        self.assertEqual(target['free_bytes_reported'], 100 * GIB)
        self.assertIn('capacity_reported_only', target['findings'])
        self.assertFalse(parsed['copy_authorized'])
        self.assertNotIn('PRIVATE-', safe_drive_report_json(result))

    def test_invalid_capacity_byte_values_are_rejected_before_copy(self):
        report = inspect(estimated=10 * GIB)
        for invalid in (-1, True, '10', 1 << 65):
            for field in ('expected_backup_bytes', 'free_bytes_reported'):
                report['destinations'][0][field] = invalid
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        safe_drive_report_json(report)
                report = inspect(estimated=10 * GIB)


class CapacityInputUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Tk indisponível: ' + str(exc))
        self.root.withdraw()
        self.addCleanup(self.cleanup_tk_on_main_thread)

    def cleanup_tk_on_main_thread(self):
        # Finalize test-owned Tcl on main thread, not on a worker GC pass.
        self.assertIs(threading.current_thread(), threading.main_thread())
        try:
            close_tk_root(self.root)
        finally:
            self.root = None
            gc.collect()

    def dialog(self):
        dlg = show_drive_safety_dialog(
            self.root, available_letters=('Q', 'R'))
        self.addCleanup(lambda: dlg.winfo_exists() and dlg.destroy())
        buttons, drives, estimates, txt = {}, [], [], []
        def descend(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Button):
                    buttons[child.cget('text')] = child
                elif isinstance(child, ttk.Entry):
                    drives.append(child)
                elif isinstance(child, tk.Entry):
                    estimates.append(child)
                elif isinstance(child, tk.Text):
                    txt.append(child)
                descend(child)
        descend(dlg)
        self.assertEqual(len(drives), 2)
        self.assertEqual(len(estimates), 1)
        self.assertEqual(len(txt), 1)
        return dlg, buttons, drives, estimates[0], txt[0]

    def choose(self, drives, size_entry, estimate='1,5'):
        drives[0].insert(0, 'Q:')
        drives[1].insert(0, 'R:')
        size_entry.insert(0, estimate)

    def wait_for(self, callback, *, seconds=5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update()
            if callback():
                return
            time.sleep(.01)
        self.fail('Tempo esgotado aguardando atualização Tk.')

    def test_variable_traces_are_unregistered_on_dialog_destroy(self):
        actual_remove = tk.StringVar.trace_remove
        calls = []

        def spy(variable, mode, callback_name):
            self.assertIs(threading.current_thread(), threading.main_thread())
            calls.append((mode, callback_name))
            return actual_remove(variable, mode, callback_name)

        with (patch.object(tk.StringVar, 'trace_remove', new=spy),
              patch('drive_safety_ui.inspect_fresh_drive_safety') as inspect):
            # Repeated open/close should not leave registered Tcl callbacks.
            for _ in range(5):
                dialog = show_drive_safety_dialog(
                    self.root, available_letters=('Q', 'R'))
                self.root.update()
                dialog.destroy()
            inspect.assert_not_called()
        self.assertEqual(len(calls), 15)
        self.assertTrue(all(mode == 'write' for mode, _ in calls))

    def test_open_does_not_consult_hardware(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as collect:
            dlg, btns, drives, size, details = self.dialog()
            self.root.update()
            collect.assert_not_called()
            self.assertEqual(str(btns['Copiar resumo seguro'].cget('state')),
                             'disabled')
            self.assertEqual(size.get(), '')

    def test_invalid_estimate_prevents_hardware_read(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as collect:
            dlg, btns, drives, size, details = self.dialog()
            self.choose(drives, size, estimate='1e9')
            btns['Conferir discos (SOMENTE LEITURA)'].invoke()
            collect.assert_not_called()
            self.assertIn('Seleção inválida', details.get('1.0', 'end'))

    def test_explicit_gib_estimate_is_passed_without_any_backup_action(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   side_effect=lambda src, dst, expected_backup_bytes:
                   inspect(estimated=expected_backup_bytes)) as collect:
            dlg, btns, drives, size, details = self.dialog()
            self.choose(drives, size, estimate='1,5')
            btns['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.wait_for(lambda:
                str(btns['Copiar resumo seguro'].cget('state')) == 'normal')
            collect.assert_called_once_with(
                ['Q'], ['R'], expected_backup_bytes=3 * GIB // 2)
            shown = details.get('1.0', 'end')
            self.assertIn('1.500 GiB', shown)
            self.assertIn('NÃO AUTORIZADOS', shown)

    def test_changing_estimate_invalidates_stale_report(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   side_effect=lambda src, dst, expected_backup_bytes:
                   inspect(estimated=expected_backup_bytes)):
            dlg, btns, drives, size, details = self.dialog()
            self.choose(drives, size)
            btns['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.wait_for(lambda:
                str(btns['Copiar resumo seguro'].cget('state')) == 'normal')
            size.delete(0, 'end')
            size.insert(0, '2')
            self.assertEqual(str(btns['Copiar resumo seguro'].cget('state')),
                             'disabled')
            self.assertIn('Seleção alterada', details.get('1.0', 'end'))

    def test_empty_estimate_preserves_legacy_two_argument_inspector(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   side_effect=lambda src, dst: inspect()) as collect:
            dlg, btns, drives, size, details = self.dialog()
            self.choose(drives, size, estimate='')
            btns['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.wait_for(lambda:
                str(btns['Copiar resumo seguro'].cget('state')) == 'normal')
            collect.assert_called_once_with(['Q'], ['R'])
            self.assertIn('não informado', details.get('1.0', 'end'))


if __name__ == '__main__':
    unittest.main()
