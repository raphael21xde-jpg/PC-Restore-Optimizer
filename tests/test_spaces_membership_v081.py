"""No real disks are opened; Storage Spaces data is simulated."""
import unittest

from spaces_membership import SPACES_QUERY, assess_spaces_membership


def disks():
    return [
        {'Number': 2, 'BusType': 'NVMe'},
        {'Number': 3, 'BusType': 'NVMe'},
        {'Number': 4, 'BusType': 'Spaces'},
    ]


def vd(*, logical=None, members=None, disk_ok=True, physical_ok=True, resilience='Simple'):
    return {
        'Name': 'Test pool virtual disk',
        'HealthStatus': 'Healthy', 'Resiliency': resilience,
        'LogicalDiskNumbers': [4] if logical is None else logical,
        'PhysicalMembers': [
            {'DeviceId': '11', 'FriendlyName': 'Sample SATA',
             'Size': 1000000000000, 'HealthStatus': 'Healthy'}
        ] if members is None else members,
        'DiskAssociationOk': disk_ok,
        'PhysicalAssociationOk': physical_ok,
    }


class SpacesMembershipTests(unittest.TestCase):
    def test_spaces_disk_number_has_one_physical_member_but_backup_unverified(self):
        result = assess_spaces_membership(disks(), [vd()])
        self.assertEqual(result['spaces_logical_disks'], [4])
        self.assertEqual(result['virtual_disks'][0]['logical_disk_numbers'], [4])
        self.assertEqual(result['virtual_disks'][0]['member_count'], 1)
        self.assertEqual(result['virtual_disks'][0]['status'], 'members_reported')
        self.assertTrue(any('tolerância a falhas' in x for x in result['issues']))
        self.assertTrue(any('backup' in x.lower() for x in result['issues']))
        self.assertFalse(result['backup_destination_verified'])
        self.assertFalse(result['approved_for_format'])

    def test_mirrored_members_are_not_treated_as_independent_backup(self):
        members = [
            {'DeviceId': '0', 'FriendlyName': 'SSD 1', 'HealthStatus': 'Healthy'},
            {'DeviceId': '1', 'FriendlyName': 'SSD 2', 'HealthStatus': 'Healthy'},
        ]
        result = assess_spaces_membership(disks(), [vd(members=members, resilience='Mirror')])
        self.assertEqual(result['virtual_disks'][0]['member_count'], 2)
        self.assertFalse(result['backup_destination_verified'])

    def test_virtual_disk_missing_association_never_safe(self):
        result = assess_spaces_membership(disks(), [vd(logical=[], disk_ok=False)])
        self.assertEqual(result['virtual_disks'][0]['status'], 'membership_incomplete')
        self.assertTrue(any('não houve associação única' in x for x in result['issues']))
        self.assertFalse(result['backup_destination_verified'])

    def test_no_members_due_to_access_denied_not_zero_physical_disks(self):
        result = assess_spaces_membership(disks(), [
            vd(members=[], physical_ok=False)])
        self.assertEqual(result['virtual_disks'][0]['status'], 'membership_incomplete')
        self.assertFalse(result['approved_for_format'])

    def test_failure_keeps_unknown_membership(self):
        result = assess_spaces_membership(disks(), [], error='AccessDenied')
        self.assertEqual(result['status'], 'requires_review')
        self.assertTrue(any('indisponível' in x for x in result['issues']))
        self.assertFalse(result['backup_destination_verified'])

    def test_multiple_matching_virtual_disks_are_ambiguous(self):
        result = assess_spaces_membership(disks(), [vd(), vd()])
        self.assertTrue(any('não houve associação única' in x for x in result['issues']))
        self.assertFalse(result['approved_for_format'])

    def test_no_spaces_does_not_trigger_false_critical_alerts(self):
        result = assess_spaces_membership([{'Number': 2, 'BusType': 'NVMe'}], [])
        self.assertEqual(result['status'], 'not_applicable')
        self.assertEqual(result['issues'], [])
        self.assertFalse(result['backup_destination_verified'])

    def test_boolean_index_and_invalid_members_are_not_trusted(self):
        item = vd(logical=[True, 4, '4'], members=[{'FriendlyName': 'SSD'}, None])
        result = assess_spaces_membership(disks(), [item])
        self.assertEqual(result['virtual_disks'][0]['logical_disk_numbers'], [4])
        self.assertEqual(result['virtual_disks'][0]['status'], 'membership_incomplete')
        self.assertFalse(result['approved_for_format'])

    def test_query_is_only_storage_reads_not_management(self):
        forbidden = ('Set-', 'Clear-', 'Remove-', 'Initialize-', 'Repair-', 'Format-',
                     'New-', 'Add-', 'Optimize-', 'Reset-', 'Start-', 'Stop-')
        for verb in forbidden:
            self.assertNotIn(verb, SPACES_QUERY)
        self.assertIn('Get-VirtualDisk', SPACES_QUERY)
        self.assertIn('Get-PhysicalDisk', SPACES_QUERY)
        self.assertIn('Get-Disk', SPACES_QUERY)


if __name__ == '__main__':
    unittest.main()
