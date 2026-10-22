"""Synthetic-only evidence test: no disk access, no real WMI/PowerShell."""
import copy
import json
import tkinter as tk
import time
import unittest
from tkinter import ttk
from unittest.mock import patch

from drive_hardware_evidence import summarize_hardware_evidence
from drive_safety_export import safe_drive_report_json
from drive_safety_report import inspect_fresh_drive_safety
from drive_safety_ui import show_drive_safety_dialog
from tk_helpers import track_tk_root


def fixture():
    return {
        'disks': [
            {'Number': 2, 'BusType': 'NVMe', 'IsBoot': True,
             'SerialNumber': 'SECRET-SYSTEM-SERIAL'},
            {'Number': 3, 'BusType': 'SATA'},
            {'Number': 4, 'BusType': 'Spaces', 'SerialNumber': 'SECRET-SPACE-SERIAL'},
        ],
        'partitions': [
            {'DriveLetter': 'C', 'DiskNumber': 2, 'IsBoot': True},
            {'DriveLetter': 'D', 'DiskNumber': 3},
            {'DriveLetter': 'G', 'DiskNumber': 4},
        ],
        'volumes': [{'DriveLetter': letter, 'SizeRemaining': 100 * 1024**3,
                     'Path': 'SECRET-GUID'} for letter in 'CDFG'],
        'extent_mapping': {'volumes': [
            {'letters': ['C'], 'disk_numbers': [2], 'status': 'logical_disk_reported'},
            {'letters': ['D'], 'disk_numbers': [3], 'status': 'logical_disk_reported'},
            {'letters': ['F'], 'disk_numbers': [1], 'status': 'disk_not_listed'},
            {'letters': ['G'], 'disk_numbers': [4], 'status': 'virtual_spaces'},
        ]},
        'spaces_membership': {
            'virtual_disks': [{
                'logical_disk_numbers': [4],
                'status': 'members_reported',
                'member_count': 2,
                'resiliency_reported': 'Mirror',
                'virtual_name': 'SECRET-VIRTUAL-POOL',
                'members': [{'device_id': 'SECRET-PHYSICAL-ID',
                             'model': 'SECRET-HARDWARE-MODEL'}],
            }],
        },
        'physical_evidence': {
            'disagreements': [{'disk_number': 1, 'present_in_wmi': True,
                               'wmi_model': 'SECRET-WMI-MODEL',
                               'wmi_status': 'OK'}],
        },
        'partition_evidence': {
            'disks_of_interest': [{
                'disk_index': 1,
                'status': 'wmi_partitions_reported',
                'partitions': [
                    {'partition_index': 0, 'type': 'SECRET-PARTITION-PATH'},
                ],
            }],
        },
    }


def inspect(data=None):
    snapshot = copy.deepcopy(fixture() if data is None else data)
    return inspect_fresh_drive_safety(
        ['C:', 'D:', 'F:'], ['G:'], collector=lambda: snapshot)


class PhysicalEvidenceReadonlyTests(unittest.TestCase):
    def test_f_unlisted_disk_uses_wmi_evidence_without_physical_claim(self):
        report = inspect()
        f = next(x for x in report['source_volumes'] if x['letter'] == 'F:')
        self.assertEqual(f['extent_status'], 'disk_not_listed')
        self.assertEqual(f['logical_disk_numbers'], [1])
        self.assertEqual(f['hardware_evidence']['wmi_diskdrive_status'], 'reported')
        self.assertEqual(f['hardware_evidence']['wmi_partition_status'], 'reported')
        self.assertEqual(f['hardware_evidence']['wmi_partition_count'], 1)
        self.assertFalse(report['copy_authorized'])

    def test_g_membership_is_observed_not_physical_verification(self):
        report = inspect()
        g = report['destinations'][0]
        evidence = g['hardware_evidence']
        self.assertEqual(g['logical_disk_numbers'], [4])
        self.assertEqual(evidence['spaces_membership_status'],
                         'members_reported_unverified')
        self.assertEqual(evidence['spaces_members_count'], 2)
        self.assertEqual(evidence['spaces_resiliency'], 'mirror')
        self.assertEqual(g['status'], 'blocked')
        for flag in ('physical_independence_verified', 'copy_authorized',
                     'ready_for_format', 'installation_authorized'):
            self.assertIs(report[flag], False)

    def test_missing_spaces_membership_never_guesses_member_count(self):
        data = fixture()
        data['spaces_membership'] = {}
        ev = inspect(data)['destinations'][0]['hardware_evidence']
        self.assertEqual(ev['spaces_membership_status'], 'not_confirmed')
        self.assertIsNone(ev['spaces_members_count'])
        self.assertIs(inspect(data)['copy_authorized'], False)

    def test_ambiguous_spaces_associations_never_pick_a_physical_pool(self):
        data = fixture()
        data['spaces_membership']['virtual_disks'].append(copy.deepcopy(
            data['spaces_membership']['virtual_disks'][0]))
        ev = inspect(data)['destinations'][0]['hardware_evidence']
        self.assertEqual(ev['spaces_membership_status'], 'ambiguous')
        self.assertIsNone(ev['spaces_members_count'])

    def test_missing_or_conflicting_wmi_matches_not_assumed_physical(self):
        data = fixture()
        data['physical_evidence']['disagreements'] = []
        ev = inspect(data)['source_volumes'][2]['hardware_evidence']
        self.assertEqual(ev['wmi_diskdrive_status'], 'not_confirmed')
        data['physical_evidence']['disagreements'] = [
            {'disk_number': 1, 'present_in_wmi': False}]
        ev = inspect(data)['source_volumes'][2]['hardware_evidence']
        self.assertEqual(ev['wmi_diskdrive_status'], 'not_reported')
        self.assertFalse(inspect(data)['physical_independence_verified'])

    def test_safe_clipboard_filters_all_raw_device_models_serials_names(self):
        shared = safe_drive_report_json(inspect())
        clean = json.loads(shared)
        f = clean['sources'][2]['hardware_evidence']
        g = clean['destinations'][0]['hardware_evidence']
        self.assertEqual(f['wmi_diskdrive_status'], 'reported')
        self.assertEqual(g['spaces_members_count'], 2)
        self.assertEqual(g['spaces_resiliency'], 'mirror')
        for private in ('SECRET-', 'device_id', 'virtual_name', 'wmi_model',
                        'SerialNumber', 'Path'):
            self.assertNotIn(private, shared)
        self.assertIs(clean['copy_authorized'], False)

    def test_unrecognized_resiliency_is_not_echoed_in_shared_report(self):
        data = fixture()
        data['spaces_membership']['virtual_disks'][0][
            'resiliency_reported'] = 'SECRET-PERSONAL-STRING'
        safe = safe_drive_report_json(inspect(data))
        self.assertEqual(json.loads(safe)['destinations'][0][
            'hardware_evidence']['spaces_resiliency'], 'unknown')
        self.assertNotIn('SECRET-', safe)

    def test_unsafe_counts_cause_safe_report_rejection(self):
        data = inspect()
        for count in (-1, 257, True, '2'):
            modified = copy.deepcopy(data)
            modified['destinations'][0]['hardware_evidence'][
                'spaces_members_count'] = count
            with self.subTest(count=count), self.assertRaises(ValueError):
                safe_drive_report_json(modified)


class PhysicalEvidenceUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Tk indisponível: ' + str(exc))
        self.root.withdraw()
        track_tk_root(self, self.root)

    def test_ui_displays_wmi_and_spaces_safely_after_explicit_click(self):
        report = inspect()
        with patch('drive_safety_ui.inspect_fresh_drive_safety', return_value=report):
            dlg = show_drive_safety_dialog(
                self.root, available_letters=('C', 'D', 'F', 'G'))
            self.addCleanup(lambda: dlg.winfo_exists() and dlg.destroy())
            buttons, entries, texts = [], [], []
            def descend(node):
                for child in node.winfo_children():
                    if isinstance(child, ttk.Button):
                        buttons.append(child)
                    if isinstance(child, ttk.Entry):
                        entries.append(child)
                    if isinstance(child, tk.Text):
                        texts.append(child)
                    descend(child)
            descend(dlg)
            self.assertEqual(len(entries), 2)
            entries[0].insert(0, 'C:,D:,F:')
            entries[1].insert(0, 'G:')
            verify = next(x for x in buttons if x.cget('text')
                          == 'Conferir discos (SOMENTE LEITURA)')
            verify.invoke()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.root.update()
                if 'Membros relatados' in texts[0].get('1.0', 'end'):
                    break
                time.sleep(.01)
            else:
                self.fail('Os dados físicos anonimizados não apareceram.')
            rendered = texts[0].get('1.0', 'end')
            self.assertIn('Win32_DiskDrive', rendered)
            self.assertIn('Win32_DiskPartition', rendered)
            self.assertIn('Storage Spaces', rendered)
            self.assertIn('NÃO AUTORIZADOS', rendered)
            self.assertNotIn('SECRET-', rendered)


if __name__ == '__main__':
    unittest.main()
