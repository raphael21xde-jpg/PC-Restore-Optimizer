"""Fixture-only Stage 43: reviewed selection size bridge, no real backup.

No physical inventory or Windows disk is ever queried. Tk dialogs use mocks.
"""
import gc
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import time
import unittest
from unittest.mock import patch

from backup_core import FileTask, Plan
from backup_capacity_input import GIB, parse_estimated_backup_gib
from preview_plan_capacity import reviewed_preview_capacity
from drive_safety_ui import show_drive_safety_dialog
from drive_safety_report import inspect_fresh_drive_safety


def file_task(drive, name, size):
    return FileTask(
        source=drive + ':\\Chosen\\' + name,
        size=size,
        mtime_ns=1234,
        destination='Chosen/' + name)


def preview():
    size_one = GIB
    size_two = GIB // 4
    return Plan(
        files=[file_task('Q', 'one.dat', size_one),
               file_task('Q', 'two.dat', size_two)],
        selected=['Q:\\Chosen'],
        skipped=['Q:\\Skip'],
        warnings=[],
        total=size_one + size_two)


def inspection(src, dst, expected_backup_bytes):
    # A fully synthetic inventory; never enumerate the real system.
    return inspect_fresh_drive_safety(
        src, dst, expected_backup_bytes=expected_backup_bytes,
        collector=lambda: {
            'disks': [
                {'Number': 10, 'BusType': 'NVMe', 'IsBoot': True},
                {'Number': 11, 'BusType': 'SATA'},
            ],
            'partitions': [
                {'DriveLetter': 'Q', 'DiskNumber': 10},
                {'DriveLetter': 'R', 'DiskNumber': 11},
            ],
            'volumes': [
                {'DriveLetter': 'Q', 'SizeRemaining': 200 * GIB},
                {'DriveLetter': 'R', 'SizeRemaining': 10 * GIB},
            ],
            'extent_mapping': {'volumes': [
                {'letters': ['Q'], 'disk_numbers': [10],
                 'status': 'logical_disk_reported'},
                {'letters': ['R'], 'disk_numbers': [11],
                 'status': 'logical_disk_reported'},
            ]},
            'spaces_membership': {},
        })


class PreviewPlanBridgeTests(unittest.TestCase):
    def test_exact_existing_preview_size_converts_without_rescanning(self):
        plan = preview()
        with (patch('os.stat', side_effect=AssertionError('No stat')),
              patch('os.scandir', side_effect=AssertionError('No scandir'))):
            result = reviewed_preview_capacity(plan, ['Q'])
        self.assertEqual(result['plan_total_bytes'], GIB + GIB // 4)
        self.assertEqual(result['size_text'], '1,250')
        self.assertEqual(result['reported_files'], 2)
        self.assertEqual(result['source_count'], 1)
        self.assertEqual(parse_estimated_backup_gib(result['size_text']),
                         result['plan_total_bytes'])

    def test_can_use_any_letters_and_multi_source_preview(self):
        plan = Plan(
            files=[file_task('D', 'app.bin', 4 * GIB),
                   file_task('Y', 'music.osz', 2 * GIB)],
            total=6 * GIB,
            selected=['D:\\Chosen', 'Y:\\Chosen'],
            skipped=[], warnings=[])
        result = reviewed_preview_capacity(plan, ['y:', 'd:'])
        self.assertEqual(result['size_text'], '6,000')
        self.assertEqual(result['source_count'], 2)

    def test_reject_partial_single_drive_preview_for_multiple_sources(self):
        with self.assertRaisesRegex(ValueError, 'não cobre'):
            reviewed_preview_capacity(preview(), ['Q', 'R'])

    def test_reject_extra_data_from_unselected_drive(self):
        plan = preview()
        plan.files.append(file_task('R', 'extra.dat', 4096))
        plan.total += 4096
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(plan, ['Q'])

    def test_reject_incomplete_plan_with_read_errors(self):
        plan = preview()
        plan.warnings.append('SENSITIVE-SOURCE-ERROR')
        with self.assertRaises(ValueError) as raised:
            reviewed_preview_capacity(plan, ['Q'])
        self.assertNotIn('SENSITIVE-', str(raised.exception))

    def test_reject_divergent_file_size_sum(self):
        plan = preview()
        plan.total += 1
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(plan, ['Q'])

    def test_reject_duplicate_file_paths_without_double_counting(self):
        plan = preview()
        plan.files.append(file_task('q', 'ONE.dat', GIB))
        plan.total += GIB
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(plan, ['Q'])

    def test_reject_missing_preview_and_no_selected_files(self):
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(None, ['Q'])
        plan = preview()
        plan.files = []
        plan.total = 0
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(plan, ['Q'])

    def test_reject_malformed_sizes_and_boolean_values(self):
        for invalid in (True, -1, '1024', 1 << 64):
            plan = preview()
            plan.files[0].size = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                reviewed_preview_capacity(plan, ['Q'])

    def test_rounds_up_to_gib_ui_precision_never_down(self):
        plan = Plan(
            files=[file_task('Z', 'tiny.bin', 1)],
            total=1, selected=['Z:\\Chosen'], warnings=[])
        value = reviewed_preview_capacity(plan, ['Z'])
        self.assertEqual(value['size_text'], '0,001')
        self.assertGreater(parse_estimated_backup_gib(value['size_text']), 1)

    def test_reject_unselected_path_on_same_drive(self):
        plan = preview()
        plan.files[0].source = 'Q:\\Other\\one.dat'
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(plan, ['Q'])

    def test_reject_drive_relative_path_even_if_drive_matches(self):
        plan = preview()
        plan.files[0].source = 'Q:relative.dat'
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(plan, ['Q'])

    def test_reject_selected_root_without_file_coverage(self):
        plan = preview()
        plan.selected.append('Q:\\Empty')
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(plan, ['Q'])

    def test_reject_path_without_drive_instead_of_guessing(self):
        plan = preview()
        plan.files[0].source = '/path/file'
        with self.assertRaises(ValueError):
            reviewed_preview_capacity(plan, ['Q'])

    def test_reject_unsafe_drive_letters_or_duplicates(self):
        for choices in (['Q', 'Q:'], [], ['C:/Windows'], ['1:']):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                reviewed_preview_capacity(preview(), choices)


class PreviewPlanCapacityUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.root.busy = False
        self.root.plan = preview()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.root is not None:
            self.root.destroy()
            self.root = None
            gc.collect()

    def open_ui(self, src='Q:', dst='R:'):
        dialog = show_drive_safety_dialog(
            self.root, available_letters=('Q', 'R'))
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        buttons, entries, details = {}, [], []
        def find(w):
            for child in w.winfo_children():
                if isinstance(child, ttk.Button):
                    buttons[child.cget('text')] = child
                if isinstance(child, ttk.Entry):
                    entries.append(child)
                elif isinstance(child, tk.Entry):
                    entries.append(child)
                if isinstance(child, tk.Text):
                    details.append(child)
                find(child)
        find(dialog)
        self.assertEqual(len(entries), 3)
        self.assertEqual(len(details), 1)
        entries[0].insert(0, src)
        entries[1].insert(0, dst)
        return dialog, buttons, entries, details[0]

    def wait_for(self, predicate):
        limit = time.monotonic() + 5
        while time.monotonic() < limit:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Dialog not updated by synthetic test.')

    def test_explicit_button_fills_size_without_disk_query(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as inspect:
            dialog, buttons, entries, details = self.open_ui()
            buttons['Usar tamanho da prévia'].invoke()
            inspect.assert_not_called()
            self.assertEqual(entries[2].get(), '1,250')
            self.assertIn('2 arquivos', details.get('1.0', 'end'))
            self.assertEqual(str(buttons['Copiar resumo seguro'].cget('state')),
                             'disabled')

    def test_partial_preview_fails_closed_without_query(self):
        self.root.plan = preview()
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as inspect:
            dialog, buttons, entries, details = self.open_ui('Q:,R:', 'S:')
            buttons['Usar tamanho da prévia'].invoke()
            inspect.assert_not_called()
            self.assertEqual(entries[2].get(), '')
            self.assertIn('Prévia indisponível ou parcial',
                          details.get('1.0', 'end'))

    def test_plan_size_is_only_passed_after_explicit_inspection_click(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   side_effect=lambda src, dst, expected_backup_bytes:
                   inspection(src, dst, expected_backup_bytes)) as inspect:
            dialog, buttons, entries, details = self.open_ui()
            buttons['Usar tamanho da prévia'].invoke()
            inspect.assert_not_called()
            buttons['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.wait_for(lambda:
                str(buttons['Copiar resumo seguro'].cget('state')) == 'normal')
            inspect.assert_called_once_with(
                ['Q'], ['R'], expected_backup_bytes=GIB + GIB // 4)
            self.assertIn('1.250 GiB', details.get('1.0', 'end'))
            self.assertIn('NÃO AUTORIZADOS', details.get('1.0', 'end'))

    def test_missing_plan_does_not_guess_or_change_selected_files(self):
        self.root.plan = None
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as inspect:
            dialog, buttons, entries, details = self.open_ui()
            buttons['Usar tamanho da prévia'].invoke()
            inspect.assert_not_called()
            self.assertIn('Prévia indisponível', details.get('1.0', 'end'))


if __name__ == '__main__':
    unittest.main()
