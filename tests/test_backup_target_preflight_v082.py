"""Backup preflight is pure metadata logic; no real disks/files are touched."""
import unittest

from backup_target_preflight import assess_backup_target, list_backup_target_candidates


def disks():
    return [
        {'Number': 1, 'BusType': 'SATA'},
        {'Number': 2, 'BusType': 'NVMe'},
        {'Number': 3, 'BusType': 'NVMe'},
        {'Number': 4, 'BusType': 'Spaces'},
    ]


def volumes():
    return [
        {'DriveLetter': 'C', 'SizeRemaining': 300_000},
        {'DriveLetter': 'D', 'SizeRemaining': 50_000},
        {'DriveLetter': 'F', 'SizeRemaining': 10_000},
        {'DriveLetter': 'G', 'SizeRemaining': 200_000},
    ]


def extents():
    return {'status': 'requires_review', 'volumes': [
        {'letters': ['C'], 'disk_numbers': [2], 'status': 'logical_disk_reported'},
        {'letters': ['D'], 'disk_numbers': [3], 'status': 'logical_disk_reported'},
        {'letters': ['F'], 'disk_numbers': [1], 'status': 'disk_not_listed'},
        {'letters': ['G'], 'disk_numbers': [4], 'status': 'virtual_spaces'},
    ]}


def membership(*, resilience='Simple', complete=True):
    return {'virtual_disks': [{
        'virtual_name': 'Espaço de armazenamento',
        'logical_disk_numbers': [4],
        'member_count': 1,
        'members': [{'model': 'HUSKY SSD 1TB', 'device_id': '0', 'health': 'Healthy'}],
        'resiliency_reported': resilience,
        'health_reported': 'Healthy',
        'status': 'members_reported' if complete else 'membership_incomplete',
    }]}


def check(letter='G', *, sources=None, estimate=None, v=None, e=None, m=None, d=None):
    return assess_backup_target(d if d is not None else disks(),
                                v if v is not None else volumes(),
                                e if e is not None else extents(),
                                m if m is not None else membership(),
                                target_letter=letter,
                                source_letters=sources,
                                expected_backup_bytes=estimate)


class BackupTargetPreflightTests(unittest.TestCase):
    def test_user_g_simple_one_husky_member_not_verified(self):
        r = check(sources=['C', 'F'], estimate=50_000)
        self.assertEqual(r['destination_logical_disks'], [4])
        self.assertEqual(r['capacity_status'], 'reported_sufficient')
        self.assertEqual(r['storage_spaces_membership'][0]['member_count_reported'], 1)
        self.assertTrue(any('Simple' in x for x in r['issues']))
        self.assertEqual(r['status'], 'requires_review')
        self.assertFalse(r['physical_independence_verified'])
        self.assertFalse(r['backup_destination_verified'])
        self.assertFalse(r['approved_for_copy'])
        self.assertFalse(r['approved_for_format'])

    def test_not_selected_never_assume_sources(self):
        r = check()
        self.assertEqual(r['source_status'], 'not_selected')
        self.assertEqual(r['capacity_status'], 'not_evaluated')
        self.assertFalse(r['approved_for_copy'])
        self.assertFalse(r['approved_for_format'])

    def test_insufficient_capacity_blocks(self):
        r = check(sources=['C'], estimate=200_001)
        self.assertEqual(r['status'], 'blocked')
        self.assertEqual(r['capacity_status'], 'insufficient')
        self.assertTrue(r['blockers'])

    def test_exact_same_drive_is_blocked(self):
        r = check(sources=['G'])
        self.assertEqual(r['status'], 'blocked')
        self.assertTrue(any('coincide' in x for x in r['blockers']))

    def test_two_letters_same_logical_disk_are_blocked(self):
        e = extents()
        e['volumes'].append({'letters': ['H'], 'disk_numbers': [4], 'status': 'virtual_spaces'})
        v = volumes() + [{'DriveLetter': 'H', 'SizeRemaining': 20_000}]
        r = check(sources=['H'], e=e, v=v)
        self.assertEqual(r['status'], 'blocked')
        self.assertTrue(any('compartilham' in x for x in r['blockers']))

    def test_different_logical_disks_cannot_prove_physical_independence(self):
        r = check(sources=['C', 'D', 'F'])
        self.assertEqual(r['status'], 'requires_review')
        self.assertFalse(r['physical_independence_verified'])
        self.assertTrue(any('NÃO comprovam' in x for x in r['issues']))

    def test_ambiguous_target_extents_stay_unknown(self):
        e = extents()
        e['volumes'].append({'letters': ['G'], 'disk_numbers': [2], 'status': 'logical_disk_reported'})
        r = check(sources=['C'], e=e, estimate=1)
        self.assertEqual(r['destination_logical_disks'], [])
        self.assertFalse(r['backup_destination_verified'])

    def test_missing_membership_is_not_zero_risk(self):
        r = check(sources=['C'], m={'virtual_disks': []})
        self.assertEqual(r['status'], 'requires_review')
        self.assertTrue(any('associação física incompleta' in x for x in r['issues']))
        self.assertFalse(r['backup_destination_verified'])

    def test_pool_mirror_healthy_not_backup(self):
        r = check(sources=['F'], m=membership(resilience='Mirror'), estimate=10)
        self.assertFalse(r['backup_integrity_verified'])
        self.assertFalse(r['approved_for_copy'])
        self.assertFalse(r['backup_destination_verified'])

    def test_zero_or_missing_free_space_is_not_certificate(self):
        r = check(sources=['C'], estimate=2, v=[
            {'DriveLetter': 'G', 'SizeRemaining': 0},
            {'DriveLetter': 'C', 'SizeRemaining': 25}
        ])
        self.assertEqual(r['capacity_status'], 'insufficient')
        r = check(sources=['C'], estimate=2, v=[{'DriveLetter': 'G'}])
        self.assertEqual(r['capacity_status'], 'unknown')

    def test_empty_source_list_is_not_selected(self):
        r = check(sources=[])
        self.assertEqual(r['source_status'], 'not_selected')

    def test_invalid_input_rejected(self):
        for args in [
            {'target_letter': '../F'},
            {'target_letter': 'G', 'source_letters': ['../C']},
            {'target_letter': 'G', 'expected_backup_bytes': -1},
            {'target_letter': 'G', 'expected_backup_bytes': True},
        ]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                assess_backup_target(disks(), volumes(), extents(), membership(), **args)

    def test_candidates_never_claim_approval(self):
        candidates = list_backup_target_candidates(disks(), volumes(), extents(), membership())
        self.assertEqual([x['target_letter'] for x in candidates], ['C', 'D', 'F', 'G'])
        self.assertTrue(all(not x['approved_for_copy'] for x in candidates))
        self.assertTrue(all(x['status'] == 'requires_review' for x in candidates))

    def test_works_without_storage_spaces(self):
        r = assess_backup_target(
            [{'Number': 2, 'BusType': 'NVMe'}, {'Number': 3, 'BusType': 'NVMe'}],
            volumes(), extents(), {}, target_letter='D',
            source_letters=['C'], expected_backup_bytes=20_000)
        self.assertFalse(r['physical_independence_verified'])
        self.assertFalse(r['approved_for_format'])


if __name__ == '__main__':
    unittest.main()
