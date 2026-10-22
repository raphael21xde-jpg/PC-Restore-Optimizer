"""Synthetic-only independent partition versus IOCTL crosschecking tests."""
import copy
import json
import tkinter as tk
from tkinter import ttk
import time
import unittest
from unittest.mock import patch

from partition_extent_crosscheck import crosscheck_partitions
from drive_safety_report import inspect_fresh_drive_safety
from drive_safety_export import safe_drive_report_json
from drive_safety_ui import show_drive_safety_dialog
from tk_helpers import track_tk_root


def snapshot():
    return {
        'disks': [
            {'Number': 2, 'BusType': 'NVMe', 'IsBoot': True, 'SerialNumber': 'NO-SERIAL-SHARE'},
            {'Number': 3, 'BusType': 'SATA'},
            {'Number': 4, 'BusType': 'Spaces'},
        ],
        'partitions': [
            {'DriveLetter': 'C', 'DiskNumber': 2, 'IsBoot': True},
            {'DriveLetter': 'D', 'DiskNumber': 3},
            {'DriveLetter': 'G', 'DiskNumber': 4},
        ],
        'volumes': [
            {'DriveLetter': x, 'SizeRemaining': 100 * 1024**3, 'Path': 'SENSITIVE-GUID'}
            for x in 'CDFG'
        ],
        'extent_mapping': {
            'volumes': [
                {'letters': ['C'], 'disk_numbers': [2],
                 'status': 'logical_disk_reported'},
                {'letters': ['D'], 'disk_numbers': [3],
                 'status': 'logical_disk_reported'},
                {'letters': ['F'], 'disk_numbers': [1],
                 'status': 'disk_not_listed'},
                {'letters': ['G'], 'disk_numbers': [4],
                 'status': 'virtual_spaces'},
            ]
        },
        'spaces_membership': {},
    }


def inspect(data=None, sources=('C:', 'D:', 'F:'), targets=('G:',)):
    doc = copy.deepcopy(data if data is not None else snapshot())
    return inspect_fresh_drive_safety(sources, targets, collector=lambda: doc)


class PartitionExtentCrosscheckTests(unittest.TestCase):
    def test_normal_logical_match_still_does_not_authorize_disk_writes(self):
        report = inspect(sources=('C:',), targets=('D:',))
        self.assertEqual(report['destinations'][0]['partition_crosscheck'],
                         'logical_match')
        self.assertEqual(report['destinations'][0]['status'], 'requires_review')
        for key in ('copy_authorized', 'physical_independence_verified',
                    'ready_for_format', 'installation_authorized'):
            self.assertIs(report[key], False)

    def test_f_extent_from_unlisted_disk_is_not_promoted_to_hardware_proof(self):
        report = inspect(sources=('F:',), targets=('D:',))
        self.assertEqual(report['source_volumes'][0]['extent_status'], 'disk_not_listed')
        self.assertEqual(report['source_volumes'][0]['partition_crosscheck'],
                         'extent_only')
        self.assertEqual(report['source_volumes'][0]['logical_disk_numbers'], [1])
        self.assertIs(report['copy_authorized'], False)

    def test_g_storage_spaces_partitions_agree_but_stays_blocked(self):
        report = inspect()
        dest = report['destinations'][0]
        self.assertEqual(dest['partition_crosscheck'], 'limited_match')
        self.assertEqual(dest['partition_logical_disk_numbers'], [4])
        self.assertEqual(dest['extent_status'], 'virtual_spaces')
        self.assertEqual(dest['status'], 'blocked')

    def test_conflicting_target_partition_is_explicitly_blocked(self):
        doc = snapshot()
        doc['partitions'][-1]['DiskNumber'] = 3
        dest = inspect(data=doc)['destinations'][0]
        self.assertEqual(dest['partition_crosscheck'], 'conflict')
        self.assertIn(3, dest['partition_logical_disk_numbers'])
        self.assertTrue(any('divergem' in b for b in dest['blockers']))
        self.assertEqual(dest['status'], 'blocked')

    def test_conflicting_source_partition_blocks_any_candidate_destination(self):
        doc = snapshot()
        doc['partitions'][1]['DiskNumber'] = 2
        report = inspect(data=doc, sources=('D:',), targets=('G:',))
        self.assertEqual(report['source_volumes'][0]['partition_crosscheck'],
                         'conflict')
        self.assertTrue(any('origem' in b.lower() and 'contraditórias' in b
                            for b in report['destinations'][0]['blockers']))
        self.assertIs(report['copy_authorized'], False)

    def test_partition_only_does_not_fill_missing_ioctl_extent(self):
        doc = snapshot()
        doc['extent_mapping']['volumes'] = [
            x for x in doc['extent_mapping']['volumes']
            if 'D' not in x['letters']]
        report = inspect(data=doc, sources=('C:',), targets=('D:',))
        dest = report['destinations'][0]
        self.assertEqual(dest['partition_crosscheck'], 'partition_only')
        self.assertEqual(dest['extent_status'], 'incomplete')
        self.assertEqual(dest['logical_disk_numbers'], [])
        self.assertEqual(dest['partition_logical_disk_numbers'], [3])
        self.assertEqual(dest['status'], 'blocked')

    def test_missing_partition_inventory_is_reported_as_unavailable(self):
        doc = snapshot()
        doc.pop('partitions')
        result = inspect(data=doc, sources=('C:',), targets=('D:',))
        dest = result['destinations'][0]
        self.assertEqual(dest['partition_crosscheck'], 'unavailable')
        self.assertEqual(dest['status'], 'requires_review')
        self.assertFalse(result['copy_authorized'])

    def test_malformed_partition_numbers_produce_inconclusive_block(self):
        doc = snapshot()
        doc['partitions'][-1]['DiskNumber'] = '4'
        result = inspect(data=doc)
        dest = result['destinations'][0]
        self.assertEqual(dest['partition_crosscheck'], 'inconclusive')
        self.assertEqual(dest['status'], 'blocked')
        self.assertTrue(any('inválida' in b for b in dest['blockers']))

    def test_partition_only_overlap_with_source_blocks_target(self):
        doc = snapshot()
        doc['partitions'][-1]['DiskNumber'] = 2
        doc['extent_mapping']['volumes'] = [
            x for x in doc['extent_mapping']['volumes']
            if 'G' not in x['letters']]
        dest = inspect(data=doc)['destinations'][0]
        self.assertEqual(dest['partition_crosscheck'], 'partition_only')
        self.assertTrue(any('compartilhamento' in b.lower()
                            for b in dest['blockers']))
        self.assertEqual(dest['status'], 'blocked')

    def test_allowlisted_share_excludes_raw_partition_rows_and_private_values(self):
        doc = snapshot()
        doc['partitions'][-1]['SerialNumber'] = 'PARTITION-PRIVATE-VALUE'
        exported = safe_drive_report_json(inspect(data=doc))
        report = json.loads(exported)
        self.assertEqual(report['destinations'][0]['partition_crosscheck'],
                         'limited_match')
        self.assertEqual(report['destinations'][0]['partition_logical_disk_numbers'], [4])
        self.assertNotIn('PARTITION-PRIVATE-VALUE', exported)
        self.assertNotIn('NO-SERIAL-SHARE', exported)
        self.assertNotIn('SENSITIVE-GUID', exported)
        self.assertFalse(report['copy_authorized'])

    def test_missing_getpartition_for_source_never_guess_f_volume_location(self):
        doc = snapshot()
        doc['partitions'] = [row for row in doc['partitions']
                             if row['DriveLetter'] != 'D']
        report = inspect(data=doc, sources=('D:',), targets=('G:',))
        self.assertEqual(report['source_volumes'][0]['partition_crosscheck'],
                         'extent_only')
        self.assertFalse(report['physical_independence_verified'])


class PartitionExtentCrosscheckUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Tk indisponível: ' + str(exc))
        self.root.withdraw()
        track_tk_root(self, self.root)

    def test_readonly_ui_displays_disagreement_without_exposing_private_identifiers(self):
        doc = snapshot()
        doc['partitions'][-1]['DiskNumber'] = 3
        report = inspect(data=doc)
        with patch('drive_safety_ui.inspect_fresh_drive_safety',
                   return_value=report):
            dlg = show_drive_safety_dialog(
                self.root, available_letters=('C', 'D', 'F', 'G'))
            self.addCleanup(lambda: dlg.winfo_exists() and dlg.destroy())
            controls = []
            fields = []
            info = []
            def visit(node):
                for child in node.winfo_children():
                    if isinstance(child, ttk.Button):
                        controls.append(child)
                    if isinstance(child, ttk.Entry):
                        fields.append(child)
                    if isinstance(child, tk.Text):
                        info.append(child)
                    visit(child)
            visit(dlg)
            for entry, value in zip(fields, ('C:,D:,F:', 'G:')):
                entry.insert(0, value)
            verify = next(x for x in controls
                          if x.cget('text') == 'Conferir discos (SOMENTE LEITURA)')
            verify.invoke()
            end = time.monotonic() + 5
            while time.monotonic() < end:
                self.root.update()
                if info and 'CONFLITO' in info[0].get('1.0', 'end'):
                    break
                time.sleep(.01)
            else:
                self.fail('A conferência de partições não apareceu na interface.')
            rendered = info[0].get('1.0', 'end')
            self.assertIn('NÃO AUTORIZADOS', rendered)
            self.assertNotIn('NO-SERIAL-SHARE', rendered)


if __name__ == '__main__':
    unittest.main()
