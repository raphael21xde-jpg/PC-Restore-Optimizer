"""Privacy-safe Windows diagnostic sharing with a synthetic collector only."""
import copy
import json
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from drive_safety_export import safe_drive_report_json, sanitized_drive_report
from drive_safety_ui import show_drive_safety_dialog


def fixture_report():
    return {
        'schema': 'pcro-readonly-drive-safety-v1',
        'status': 'requires_review',
        'inventory_status': 'fresh_collected',
        'source_volumes': [{
            'letter': 'C:', 'logical_disk_numbers': [0],
            'extent_status': 'observed_logical_only',
            'SerialNumber': 'SECRET-ORIGIN-SERIAL',
        }],
        'destinations': [{
            'letter': 'G:', 'logical_disk_numbers': [3],
            'extent_status': 'observed_logical_only',
            'capacity_status': 'not_evaluated',
            'status': 'requires_review', 'blockers': [],
            'issues': ['Sensitive notes: PRIVATE-USER-MODEL-XYZ'],
            'Path': 'SECRET-DESTINATION-GUID',
        }],
        'boot_related_logical_disks': [0],
        'raw_identifiers_included': False,
        'physical_independence_verified': False,
        'backup_verified': False,
        'copy_authorized': False,
        'ready_for_format': False,
        'installation_authorized': False,
        'SerialNumber': 'SECRET-ROOT-SERIAL',
        'alerts': ['SECRET-PRIVATE-ALERT'],
        'nt_volume_mapping': {'nt_device': 'SECRET-NTPATH'},
    }


class SafeHardwareReportTests(unittest.TestCase):
    def test_only_allowlisted_fields_are_exported_without_serials(self):
        safe = sanitized_drive_report(fixture_report())
        text = json.dumps(safe, ensure_ascii=False)
        for secret in ('SECRET-ORIGIN-SERIAL', 'SECRET-DESTINATION-GUID',
                       'SECRET-ROOT-SERIAL', 'SECRET-PRIVATE-ALERT',
                       'SECRET-NTPATH', 'PRIVATE-USER-MODEL-XYZ'):
            self.assertNotIn(secret, text)
        self.assertEqual(safe['sources'][0]['letter'], 'C:')
        self.assertEqual(safe['destinations'][0]['logical_disk_numbers'], [3])
        self.assertEqual(safe['boot_related_logical_disks'], [0])
        self.assertFalse(safe['copy_authorized'])
        self.assertFalse(safe['installation_authorized'])

    def test_safe_json_roundtrip_contains_no_raw_power_shell_fields(self):
        parsed = json.loads(safe_drive_report_json(fixture_report()))
        self.assertEqual(parsed['schema'], 'pcro-drive-diagnostic-safe-share-v1')
        self.assertEqual(parsed['destinations'][0]['capacity_status'], 'not_evaluated')
        self.assertEqual(parsed['destinations'][0]['blocker_count'], 0)
        self.assertNotIn('SerialNumber', parsed)
        self.assertNotIn('alerts', parsed)
        self.assertFalse(parsed['ready_for_format'])

    def test_unauthorized_approval_flags_are_rejected(self):
        for key in ('copy_authorized', 'backup_verified',
                    'physical_independence_verified', 'ready_for_format',
                    'installation_authorized'):
            row = fixture_report()
            row[key] = True
            with self.subTest(key=key), self.assertRaises(ValueError):
                safe_drive_report_json(row)

    def test_raw_identifiers_flag_or_wrong_schema_is_rejected(self):
        item = fixture_report()
        item['raw_identifiers_included'] = True
        with self.assertRaises(ValueError):
            safe_drive_report_json(item)
        item = fixture_report()
        item['schema'] = 'unexpected'
        with self.assertRaises(ValueError):
            safe_drive_report_json(item)

    def test_invalid_disk_numbers_rejected_instead_of_dumping_inventory(self):
        for invalid in ([True], [-1], [65536], ['3'], [1, 1]):
            item = fixture_report()
            item['destinations'][0]['logical_disk_numbers'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                safe_drive_report_json(item)

    def test_malformed_target_fields_cannot_bypass_privacy_filter(self):
        item = fixture_report()
        item['destinations'][0]['letter'] = r'C:\Sensitive\Path'
        with self.assertRaises(ValueError):
            safe_drive_report_json(item)
        item = fixture_report()
        item['destinations'][0]['capacity_status'] = 'serial-SECRET'
        with self.assertRaises(ValueError):
            safe_drive_report_json(item)


class SafeHardwareReportUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk indisponível: {exc}')
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def make_dialog(self):
        dlg = show_drive_safety_dialog(
            self.root, available_letters=('C', 'G'))
        self.addCleanup(lambda: dlg.winfo_exists() and dlg.destroy())
        widgets = []
        def descend(node):
            for child in node.winfo_children():
                widgets.append(child)
                descend(child)
        descend(dlg)
        buttons = {w.cget('text'): w for w in widgets
                   if isinstance(w, ttk.Button)}
        entries = [w for w in widgets if isinstance(w, ttk.Entry)]
        return dlg, buttons, entries

    def wait_for(self, predicate, limit=5):
        finish = time.monotonic() + limit
        while time.monotonic() < finish:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Tempo esgotado ao aguardar a interface.')

    def choose(self, entries, source='C:', target='G:'):
        for widget, value in zip(entries, (source, target)):
            widget.delete(0, 'end')
            widget.insert(0, value)

    def test_copy_requires_completed_explicit_hardware_diagnostic(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as inspector:
            dlg, buttons, entries = self.make_dialog()
            self.root.update()
            self.assertEqual(
                str(buttons['Copiar resumo seguro'].cget('state')), 'disabled')
            buttons['Copiar resumo seguro'].invoke()
            inspector.assert_not_called()

    def test_copies_safe_json_only_after_successful_diagnostic(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   return_value=fixture_report()) as inspector:
            dlg, buttons, entries = self.make_dialog()
            self.choose(entries)
            buttons['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.wait_for(lambda:
                          str(buttons['Copiar resumo seguro'].cget('state'))
                          == 'normal')
            with (patch.object(dlg, 'clipboard_clear') as clear,
                  patch.object(dlg, 'clipboard_append') as append):
                buttons['Copiar resumo seguro'].invoke()
            inspector.assert_called_once_with(['C'], ['G'])
            clear.assert_called_once()
            append.assert_called_once()
            copied = append.call_args.args[0]
            parsed = json.loads(copied)
            self.assertEqual(parsed['sources'][0]['letter'], 'C:')
            self.assertNotIn('SECRET-', copied)
            self.assertNotIn('PRIVATE-USER-MODEL', copied)
            self.assertFalse(parsed['copy_authorized'])

    def test_invalid_new_selection_invalidates_previous_copy(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   return_value=fixture_report()) as inspector:
            dlg, buttons, entries = self.make_dialog()
            self.choose(entries)
            buttons['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.wait_for(lambda:
                          str(buttons['Copiar resumo seguro'].cget('state'))
                          == 'normal')
            self.choose(entries, source='C:', target='C:')
            buttons['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.assertEqual(
                str(buttons['Copiar resumo seguro'].cget('state')), 'disabled')
            inspector.assert_called_once()

    def test_failed_new_collection_invalidates_previous_copy(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   side_effect=[fixture_report(), RuntimeError('PRIVATE-SERIAL')]):
            dlg, buttons, entries = self.make_dialog()
            self.choose(entries)
            buttons['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.wait_for(lambda:
                          str(buttons['Copiar resumo seguro'].cget('state'))
                          == 'normal')
            buttons['Conferir discos (SOMENTE LEITURA)'].invoke()
            self.assertEqual(
                str(buttons['Copiar resumo seguro'].cget('state')), 'disabled')
            self.wait_for(lambda:
                          str(buttons['Conferir discos (SOMENTE LEITURA)'].cget('state'))
                          == 'normal')
            self.assertEqual(
                str(buttons['Copiar resumo seguro'].cget('state')), 'disabled')


if __name__ == '__main__':
    unittest.main()
