"""Stage 40: static warnings for any disk letters; all fixtures are synthetic."""
import copy
import json
import tkinter as tk
from tkinter import ttk
import time
import unittest
from unittest.mock import patch

from drive_diagnostic_advice import FINDING_TEXT, classify_drive_findings
from drive_safety_export import safe_drive_report_json
from drive_safety_report import inspect_fresh_drive_safety
from drive_safety_ui import show_drive_safety_dialog
from tk_helpers import track_tk_root


def fixture():
    return {
        'disks': [
            {'Number': 8, 'BusType': 'NVMe', 'IsBoot': True,
             'SerialNumber': 'PRIVATE-DISK-IDENTIFIER'},
            {'Number': 9, 'BusType': 'SATA'},
            {'Number': 11, 'BusType': 'Spaces'},
        ],
        'partitions': [
            {'DriveLetter': 'Q', 'DiskNumber': 8, 'IsBoot': True},
            {'DriveLetter': 'R', 'DiskNumber': 9},
            {'DriveLetter': 'T', 'DiskNumber': 11},
        ],
        'volumes': [
            {'DriveLetter': v, 'SizeRemaining': 50 * 1024 ** 3,
             'Path': 'PRIVATE-VOLUME-GUID'}
            for v in 'QRST'
        ],
        'extent_mapping': {
            'volumes': [
                {'letters': ['Q'], 'disk_numbers': [8],
                 'status': 'logical_disk_reported'},
                {'letters': ['R'], 'disk_numbers': [9],
                 'status': 'logical_disk_reported'},
                {'letters': ['S'], 'disk_numbers': [10],
                 'status': 'disk_not_listed'},
                {'letters': ['T'], 'disk_numbers': [11],
                 'status': 'virtual_spaces'},
            ],
        },
        'spaces_membership': {
            'virtual_disks': [{
                'logical_disk_numbers': [11],
                'status': 'members_reported',
                'member_count': 1,
                'resiliency_reported': 'Simple',
                'virtual_name': 'PRIVATE-POOL-NAME',
                'members': [{'device_id': 'PRIVATE-MEMBER'}],
            }],
        },
        'physical_evidence': {
            'disagreements': [{
                'disk_number': 10,
                'present_in_wmi': True,
                'wmi_model': 'PRIVATE-MODEL',
            }],
        },
        'partition_evidence': {
            'disks_of_interest': [{
                'disk_index': 10,
                'status': 'wmi_partitions_reported',
                'partitions': [
                    {'partition_index': i, 'type': 'PRIVATE-PARTITION'}
                    for i in range(6)
                ],
            }],
        },
    }


def inspect(data=None, sources=('Q:', 'R:', 'S:'), targets=('T:',)):
    snapshot = copy.deepcopy(fixture() if data is None else data)
    return inspect_fresh_drive_safety(
        sources, targets, collector=lambda: snapshot)


class StorageRiskGuidanceTests(unittest.TestCase):
    def test_unlisted_wmi_disk_with_partitions_is_not_called_empty(self):
        report = inspect()
        item = next(v for v in report['source_volumes']
                    if v['letter'] == 'S:')
        self.assertIn('unlisted_disk_wmi_partitions', item['findings'])
        self.assertIn('não listou', FINDING_TEXT['unlisted_disk_wmi_partitions'])
        self.assertEqual(item['hardware_evidence']['wmi_partition_count'], 6)

    def test_simple_one_member_warns_about_no_redundancy(self):
        result = inspect()
        item = result['destinations'][0]
        self.assertIn('spaces_simple_single_member', item['findings'])
        self.assertIn('spaces_members_unverified', item['findings'])
        self.assertIn('não há redundância',
                      FINDING_TEXT['spaces_simple_single_member'])
        self.assertEqual(item['status'], 'blocked')

    def test_simple_multi_member_still_no_redundancy(self):
        data = fixture()
        data['spaces_membership']['virtual_disks'][0]['member_count'] = 2
        item = inspect(data)['destinations'][0]
        self.assertIn('spaces_simple_no_redundancy', item['findings'])
        self.assertNotIn('spaces_simple_single_member', item['findings'])

    def test_mirror_does_not_imply_backup_destination_approval(self):
        data = fixture()
        data['spaces_membership']['virtual_disks'][0]['resiliency_reported'] = 'Mirror'
        data['spaces_membership']['virtual_disks'][0]['member_count'] = 2
        result = inspect(data)
        findings = result['destinations'][0]['findings']
        self.assertNotIn('spaces_simple_single_member', findings)
        self.assertNotIn('spaces_simple_no_redundancy', findings)
        self.assertIn('spaces_members_unverified', findings)
        self.assertFalse(result['copy_authorized'])

    def test_missing_pool_evidence_does_not_claim_single_member(self):
        data = fixture()
        data['spaces_membership'] = {}
        item = inspect(data)['destinations'][0]
        self.assertIn('spaces_members_unknown', item['findings'])
        self.assertNotIn('spaces_simple_single_member', item['findings'])

    def test_boot_disk_risk_does_not_depend_on_drive_letter(self):
        item = inspect()['source_volumes'][0]
        self.assertEqual(item['letter'], 'Q:')
        self.assertIn('boot_dependency_reported', item['findings'])

    def test_partition_conflict_is_reported_as_warning(self):
        data = fixture()
        data['partitions'][-1]['DiskNumber'] = 9
        target = inspect(data)['destinations'][0]
        self.assertIn('partition_extent_conflict', target['findings'])
        self.assertEqual(target['status'], 'blocked')

    def test_unevaluated_capacity_and_blocked_target_not_silently_approved(self):
        result = inspect()
        item = result['destinations'][0]
        self.assertIn('capacity_not_evaluated', item['findings'])
        self.assertIn('backup_target_blocked', item['findings'])
        self.assertFalse(result['ready_for_format'])
        self.assertFalse(result['installation_authorized'])
        self.assertFalse(result['physical_independence_verified'])

    def test_advice_never_includes_any_raw_hardware_value(self):
        report = inspect()
        safe = safe_drive_report_json(report)
        parsed = json.loads(safe)
        assert parsed['destinations'][0]['findings']
        for private in ('PRIVATE-', 'serial', 'virtual_name', 'members',
                        'wmi_model', 'device_id'):
            if private == 'members':
                # The explicitly allowed numeric member count is public, not
                # a private member list.
                self.assertNotIn('"members"', safe)
            else:
                self.assertNotIn(private, safe)
        self.assertFalse(parsed['copy_authorized'])

    def test_invalid_finding_strings_or_duplicates_are_rejected(self):
        for invalid in (['PRIVATE-SERIAL'], ['backup_target_blocked'] * 2,
                        'unlisted_disk_unknown', [999]):
            report = inspect()
            report['destinations'][0]['findings'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                safe_drive_report_json(report)

    def test_unknown_or_old_report_without_findings_stays_compatible(self):
        report = inspect()
        del report['source_volumes'][0]['findings']
        del report['destinations'][0]['findings']
        exported = json.loads(safe_drive_report_json(report))
        self.assertEqual(exported['sources'][0]['findings'], [])
        self.assertEqual(exported['destinations'][0]['findings'], [])

    def test_findings_do_not_allow_any_disk_operation(self):
        result = inspect()
        for key in ('physical_independence_verified', 'backup_verified',
                    'copy_authorized', 'ready_for_format',
                    'installation_authorized'):
            self.assertIs(result[key], False)


class StorageRiskGuidanceUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Tk indisponível: ' + str(exc))
        self.root.withdraw()
        track_tk_root(self, self.root)

    def test_ui_shows_plain_language_risks_for_nonstandard_letters(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   return_value=inspect()):
            dialog = show_drive_safety_dialog(
                self.root, available_letters=('Q', 'R', 'S', 'T'))
            self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
            entries, buttons, details = [], [], []
            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Entry):
                        entries.append(child)
                    if isinstance(child, ttk.Button):
                        buttons.append(child)
                    if isinstance(child, tk.Text):
                        details.append(child)
                    walk(child)
            walk(dialog)
            self.assertEqual(len(entries), 2)
            entries[0].insert(0, 'Q:,R:,S:')
            entries[1].insert(0, 'T:')
            next(b for b in buttons if b.cget('text')
                 == 'Conferir discos (SOMENTE LEITURA)').invoke()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.root.update()
                if details and 'não há redundância' in details[0].get('1.0', 'end'):
                    break
                time.sleep(.01)
            else:
                self.fail('Os avisos de risco não apareceram.')
            displayed = details[0].get('1.0', 'end')
            self.assertIn('Win32_DiskDrive', displayed)
            self.assertIn('partições', displayed)
            self.assertIn('NÃO AUTORIZADOS', displayed)
            self.assertNotIn('PRIVATE-', displayed)


if __name__ == '__main__':
    unittest.main()
