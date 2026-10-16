"""Read-only WMI partition details and BCDEdit failure classification."""
import unittest

from boot_physical_evidence import classify_bcd_output
from wmi_partition_evidence import summarize_wmi_partitions


class WmiPartitionAndBcdTests(unittest.TestCase):
    def test_wmi_reports_disk_one_partitions_without_certifying_efi(self):
        r = summarize_wmi_partitions([
            {'DiskIndex': 1, 'Index': 0, 'Type': 'GPT: System', 'Size': 104857600, 'BootPartition': False},
            {'DiskIndex': 1, 'Index': 1, 'Type': 'Installable File System',
             'Size': 238000000000, 'BootPartition': True},
            {'DiskIndex': 2, 'Index': 2, 'Type': 'Recovery Partition', 'Size': 550000000},
        ], disk_numbers_of_interest=[1])
        self.assertEqual(len(r['disks_of_interest']), 1)
        self.assertEqual(len(r['disks_of_interest'][0]['partitions']), 2)
        self.assertTrue(r['disks_of_interest'][0]['partitions'][0]['efi_type_candidate'])
        self.assertTrue(r['disks_of_interest'][0]['partitions'][1]['boot_partition_hint'])
        self.assertFalse(r['efi_active_verified'])
        self.assertFalse(r['approved_for_format'])
        self.assertFalse(r['backup_destination_verified'])

    def test_unreported_disk_is_unknown(self):
        r = summarize_wmi_partitions([], disk_numbers_of_interest=[1])
        self.assertEqual(r['disks_of_interest'][0]['status'], 'not_reported')
        self.assertEqual(r['status'], 'requires_review')
        self.assertFalse(r['approved_for_format'])

    def test_wmi_failure_is_explicit(self):
        r = summarize_wmi_partitions([], disk_numbers_of_interest=[1], error='AccessDenied')
        self.assertEqual(r['status'], 'partial')
        self.assertTrue(r['issues'])

    def test_boolean_disk_indices_rejected(self):
        r = summarize_wmi_partitions([
            {'DiskIndex': True, 'Index': 0, 'Type': 'GPT: System'},
            {'DiskIndex': '1', 'Index': 1, 'Type': 'GPT: System'},
        ], disk_numbers_of_interest=[1, True, '2'])
        self.assertEqual(r['disks_of_interest'][0]['partitions'], [])

    def test_user_bcd_device_volume5_is_not_disk5(self):
        bcd = ('Gerenciador de Inicialização do Windows\n'
               'device                  partition=\\Device\\HarddiskVolume5\n'
               'path                    \\EFI\\MICROSOFT\\BOOT\\BOOTMGFW.EFI\n')
        r = classify_bcd_output(bcd)
        self.assertEqual(r['nt_volume_devices'], ['\\device\\harddiskvolume5'])
        self.assertEqual(r['reason'], 'none')
        self.assertFalse(r['efi_active_verified'])
        self.assertFalse(r['approved_for_format'])

    def test_bcd_access_denied_classification(self):
        r = classify_bcd_output(returncode=1,
                                stderr='O repositório BCD não pôde ser aberto. Acesso negado.')
        self.assertEqual(r['reason'], 'permission_denied')
        self.assertEqual(r['status'], 'unavailable')
        self.assertFalse(r['approved_for_format'])

    def test_bcd_nonzero_without_detail_stays_unknown(self):
        r = classify_bcd_output(returncode=1)
        self.assertEqual(r['reason'], 'query_failed')

    def test_bcd_tool_missing_is_not_permissions(self):
        r = classify_bcd_output(error='tool_missing')
        self.assertEqual(r['reason'], 'tool_missing')

    def test_timeout_is_not_silent(self):
        r = classify_bcd_output(error='timeout')
        self.assertEqual(r['reason'], 'timeout')


if __name__ == '__main__':
    unittest.main()
