"""Firmware order tests: simulated data, no BCD/EFI/disk modifications."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import firmware_order_evidence as fw

FM = '{11111111-1111-1111-1111-111111111111}'
BOOT = '{22222222-2222-2222-2222-222222222222}'
OTHER = '{33333333-3333-3333-3333-333333333333}'
BOOT2 = '{44444444-4444-4444-4444-444444444444}'


def firmware_text(*, locale='pt', two_orders=False, second_bootmgr=False, wrong_path=False):
    fhead = 'Gerenciador de Inicialização de Firmware' if locale == 'pt' else 'Firmware Boot Manager'
    bhead = 'Gerenciador de Inicialização do Windows' if locale == 'pt' else 'Windows Boot Manager'
    key = 'identificador' if locale == 'pt' else 'identifier'
    path = r'\EFI\MICROSOFT\BOOT\BOOTMGFW.EFI' if not wrong_path else r'\EFI\EXAMPLE\OTHER.EFI'
    extra_order = ('\n                        ' + (BOOT2 if second_bootmgr else OTHER)) if two_orders else ''
    extra_entry = ('\n\nWindows Boot Manager\n--------------------\n'
                   f'{key}           {BOOT2}\n'
                   r'device          partition=\Device\HarddiskVolume7' '\n'
                   r'path            \EFI\MICROSOFT\BOOT\BOOTMGFW.EFI' '\n') if second_bootmgr else ''
    return (f'{fhead}\n----------------------------------------\n'
            f'{key}           {FM}\n'
            f'displayorder       {BOOT}{extra_order}\n'
            'timeout            1\n\n'
            f'{bhead}\n----------------------------------------\n'
            f'{key}           {BOOT}\n'
            r'device              partition=\Device\HarddiskVolume5' '\n'
            f'path                {path}\n'
            'description          Windows Boot Manager\n'
            'displayorder        {55555555-5555-5555-5555-555555555555}\n'
            + extra_entry)


def nt_mapping():
    return {'volumes': [
        {'nt_device': r'\Device\HarddiskVolume5', 'disk_numbers': [1], 'status': 'observed'},
        {'nt_device': r'\Device\HarddiskVolume7', 'disk_numbers': [3], 'status': 'observed'},
    ]}


class FirmwareOrderEvidenceTests(unittest.TestCase):
    def test_portuguese_user_topology_registered_cross_disk_not_bootcurrent(self):
        result = fw.assess_firmware_order(firmware_text(), nt_mapping(), {'boot_disks': [2]})
        self.assertEqual(result['status'], 'registered_bootmgr_cross_disk')
        self.assertEqual(result['order_entry_count'], 1)
        self.assertEqual(result['bootmgr_nt_device'], r'\device\harddiskvolume5')
        self.assertEqual(result['bootmgr_disks'], [1])
        self.assertEqual(result['windows_disks'], [2])
        self.assertTrue(result['bootmgr_in_order'])
        self.assertFalse(result['bootcurrent_verified'])
        self.assertFalse(result['efi_active_verified'])
        self.assertFalse(result['backup_destination_verified'])
        self.assertFalse(result['approved_for_format'])
        self.assertNotIn(BOOT.lower(), str(result))

    def test_english_firmware_multiple_registered_entries_not_bootcurrent(self):
        result = fw.assess_firmware_order(
            firmware_text(locale='en', two_orders=True), nt_mapping(), {'boot_disks': [2]})
        self.assertEqual(result['status'], 'registered_bootmgr_cross_disk')
        self.assertEqual(result['order_entry_count'], 2)
        self.assertFalse(result['bootcurrent_verified'])

    def test_same_disk_still_never_safe(self):
        result = fw.assess_firmware_order(firmware_text(), nt_mapping(), {'boot_disks': [1]})
        self.assertEqual(result['status'], 'registered_bootmgr_same_disk')
        self.assertFalse(result['efi_active_verified'])
        self.assertFalse(result['approved_for_format'])

    def test_incorrect_path_not_assumed_bootmgr(self):
        result = fw.assess_firmware_order(
            firmware_text(wrong_path=True), nt_mapping(), {'boot_disks': [2]})
        self.assertEqual(result['status'], 'bootmgr_not_unique_in_order')
        self.assertFalse(result['bootmgr_in_order'])
        self.assertFalse(result['approved_for_format'])

    def test_two_bootmgr_entries_are_ambiguous(self):
        result = fw.assess_firmware_order(
            firmware_text(two_orders=True, second_bootmgr=True),
            nt_mapping(), {'boot_disks': [2]})
        self.assertEqual(result['status'], 'bootmgr_not_unique_in_order')

    def test_missing_or_truncated_firmware_is_unknown(self):
        for text in ('', 'corrupted', ' ' * (fw.MAX_TEXT + 1)):
            with self.subTest(size=len(text)):
                result = fw.assess_firmware_order(text, nt_mapping(), {'boot_disks': [2]})
                self.assertEqual(result['status'], 'unavailable')
                self.assertFalse(result['approved_for_format'])

    def test_missing_nt_mapping_is_unknown_disk(self):
        result = fw.assess_firmware_order(firmware_text(), {}, {'boot_disks': [2]})
        self.assertEqual(result['status'], 'registered_bootmgr_disk_unknown')
        self.assertEqual(result['bootmgr_disks'], [])
        self.assertFalse(result['approved_for_format'])

    def test_multiple_nt_alias_results_are_ambiguous(self):
        both = nt_mapping()
        both['volumes'].append({'nt_device': r'\Device\HarddiskVolume5',
                                'disk_numbers': [4], 'status': 'observed'})
        result = fw.assess_firmware_order(firmware_text(), both, {'boot_disks': [2]})
        self.assertEqual(result['status'], 'registered_bootmgr_disk_unknown')

    def test_only_read_flags_no_privilege_elevation(self):
        captured = {}
        def runner(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            return SimpleNamespace(returncode=0, stdout=firmware_text(), stderr='')
        with patch.object(fw.os, 'name', 'nt'), patch.object(fw.shutil, 'which',
                                                           return_value='bcdedit.exe'):
            result = fw.collect_firmware_order(nt_mapping(), {'boot_disks': [2]}, runner=runner)
        self.assertEqual(captured['command'][1:], ['/enum', 'firmware', '/v'])
        self.assertEqual(captured['kwargs']['timeout'], 12)
        self.assertEqual(result['status'], 'registered_bootmgr_cross_disk')
        self.assertNotIn('/set', captured['command'])
        self.assertNotIn('/delete', captured['command'])

    def test_access_denied_does_not_claim_efi(self):
        def runner(command, **kwargs):
            return SimpleNamespace(returncode=1, stdout='',
                                   stderr='O repositório BCD não pôde ser aberto. Acesso negado.')
        with patch.object(fw.os, 'name', 'nt'), patch.object(fw.shutil, 'which',
                                                           return_value='bcdedit.exe'):
            result = fw.collect_firmware_order(nt_mapping(), {'boot_disks': [2]}, runner=runner)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'permission_denied')
        self.assertFalse(result['bootcurrent_verified'])

    def test_timeout_keeps_uncertainty(self):
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        with patch.object(fw.os, 'name', 'nt'), patch.object(fw.shutil, 'which',
                                                           return_value='bcdedit.exe'):
            result = fw.collect_firmware_order(nt_mapping(), {'boot_disks': [2]}, runner=runner)
        self.assertEqual(result['reason'], 'timeout')
        self.assertFalse(result['approved_for_format'])


if __name__ == '__main__':
    unittest.main()
