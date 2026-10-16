import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import boot_physical_evidence as be


class ReadOnlyBootAndPhysicalEvidenceTests(unittest.TestCase):
    def test_bcd_enum_observed_but_efi_not_verified(self):
        bcd = 'Windows Boot Manager\nidentifier {bootmgr}\ndevice partition=\\Device\\HarddiskVolume4\n'
        r = be.classify_bcd_output(bcd)
        self.assertEqual(r['status'], 'bootmgr_store_observed')
        self.assertEqual(r['nt_volume_devices'], ['\\device\\harddiskvolume4'])
        self.assertFalse(r['efi_active_verified'])
        self.assertFalse(r['approved_for_format'])

    def test_bcd_denied_or_unknown_stays_unknown(self):
        for args in ({'returncode': 1}, {'error': 'requires elevation'}):
            with self.subTest(args=args):
                r = be.classify_bcd_output('bootmgr', **args)
                self.assertEqual(r['status'], 'unavailable')
                self.assertFalse(r['efi_active_verified'])
                self.assertFalse(r['approved_for_format'])

    def test_bcd_read_only_flags_and_timeout(self):
        captured = {}
        def runner(cmd, **kwargs):
            captured.update(cmd=cmd, kwargs=kwargs)
            return SimpleNamespace(returncode=0, stdout='device partition=\\Device\\HarddiskVolume2')
        with patch.object(be.os, 'name', 'nt'), patch.object(be.shutil, 'which', return_value='bcdedit.exe'):
            r = be.collect_bcd_evidence(runner=runner)
        self.assertEqual(captured['cmd'][1:], ['/enum', 'BOOTMGR', '/v'])
        self.assertEqual(captured['kwargs']['timeout'], 12)
        self.assertEqual(r['status'], 'bootmgr_store_observed')
        self.assertNotIn('/set', captured['cmd'])

    def test_bcd_timeout_does_not_elevate(self):
        def runner(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs['timeout'])
        with patch.object(be.os, 'name', 'nt'), patch.object(be.shutil, 'which', return_value='bcdedit.exe'):
            r = be.collect_bcd_evidence(runner=runner)
        self.assertEqual(r['status'], 'unavailable')

    def test_missing_getdisk_but_wmi_index_available(self):
        disks = [{'Number': 2}, {'Number': 4}]
        wmi = [{'Index': 1, 'Model': 'Test device', 'Status': 'OK'}]
        extents = {'volumes': [{'disk_numbers': [1], 'status': 'disk_not_listed'}]}
        r = be.reconcile_diskdrive_evidence(disks, wmi, extents)
        self.assertEqual(r['getdisk_missing_extent_numbers'], [1])
        self.assertTrue(r['disagreements'][0]['present_in_wmi'])
        self.assertFalse(r['efi_active_verified'])
        self.assertFalse(r['backup_destination_verified'])
        self.assertFalse(r['approved_for_format'])

    def test_disk_absent_from_both_sources_is_not_declared_removed(self):
        r = be.reconcile_diskdrive_evidence([{'Number': 2}], [],
                         {'volumes': [{'disk_numbers': [1], 'status': 'disk_not_listed'}]},
                         wmi_error='AccessDenied')
        self.assertEqual(r['disagreements'][0]['present_in_wmi'], False)
        self.assertTrue(any('não apareceu' in x for x in r['issues']))
        self.assertFalse(r['backup_destination_verified'])

    def test_same_numbers_never_grant_backup_or_format(self):
        r = be.reconcile_diskdrive_evidence([{'Number': 1}], [{'Index': 1}],
                         {'volumes': [{'disk_numbers': [1]}]})
        self.assertEqual(r['getdisk_missing_extent_numbers'], [])
        self.assertFalse(r['backup_destination_verified'])
        self.assertFalse(r['approved_for_format'])

    def test_invalid_disk_ids_never_become_evidence(self):
        r = be.reconcile_diskdrive_evidence([{'Number': True}], [{'Index': '1'}],
                                            {'volumes': [{'disk_numbers': [True, '1', -1]}]})
        self.assertEqual(r['getdisk_missing_extent_numbers'], [])

    def test_non_windows_never_queries_bcd(self):
        with patch.object(be.os, 'name', 'posix'):
            self.assertEqual(be.collect_bcd_evidence()['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
