"""Read-only scenario tests grounded in the user's observed C/D/F/G inventory.

No hardware is accessed or modified; this suite uses Python mock records.
"""
import unittest

from backup_preflight_scenario import GIB, parse_gib, scenario_text, simulate_backup_preflight


def snapshot():
    return {
        'disks': [
            {'Number': 2, 'BusType': 'NVMe', 'IsBoot': True},
            {'Number': 3, 'BusType': 'NVMe'},
            {'Number': 4, 'BusType': 'Spaces'},
        ],
        'volumes': [
            {'DriveLetter': 'C', 'SizeRemaining': 137604915200},
            {'DriveLetter': 'D', 'SizeRemaining': 90384388096},
            {'DriveLetter': 'F', 'SizeRemaining': 67531210752},
            {'DriveLetter': 'G', 'SizeRemaining': 172021538816},
        ],
        'extent_mapping': {'volumes': [
            {'letters': ['C'], 'disk_numbers': [2], 'status': 'logical_disk_reported'},
            {'letters': ['D'], 'disk_numbers': [3], 'status': 'logical_disk_reported'},
            {'letters': ['F'], 'disk_numbers': [1], 'status': 'disk_not_listed'},
            {'letters': ['G'], 'disk_numbers': [4], 'status': 'virtual_spaces'},
        ]},
        'spaces_membership': {'virtual_disks': [{
            'virtual_name': 'Espaço de armazenamento',
            'logical_disk_numbers': [4],
            'resiliency_reported': 'Simple',
            'member_count': 1,
            'status': 'members_reported',
            'members': [{'model': 'HUSKY SSD 1TB',
                         'device_id': '0', 'health': 'Healthy'}],
        }]},
        'boot_layout': {'boot_disks': [2]},
        'boot_dependency': {'status': 'separate_disks_reported',
                            'bootmgr_disk_numbers': [1]},
        'firmware_order': {'status': 'registered_bootmgr_cross_disk',
                           'bootmgr_disks': [1]},
    }


class ScenarioTests(unittest.TestCase):
    def simulate(self, source=('C',), target='G', size='20', data=None):
        return simulate_backup_preflight(data or snapshot(),
            source_letters=list(source), target_letter=target, estimate_gib=size)

    def test_g_source_c_20_gib_review_with_pool_simple_warning(self):
        result = self.simulate()
        self.assertEqual(result['status'], 'requires_review')
        self.assertEqual(result['capacity_status'], 'reported_sufficient_with_reserve')
        self.assertEqual(result['expected_backup_bytes'], 20 * GIB)
        self.assertEqual(result['source_letters'], ['C'])
        self.assertIn('spaces_simple', result['risk_tags'])
        self.assertFalse(result['backup_destination_verified'])
        self.assertFalse(result['physical_independence_verified'])
        self.assertFalse(result['approved_for_copy'])
        self.assertFalse(result['approved_for_format'])
        self.assertIn('SIMULAÇÃO DE DESTINO', scenario_text(result))

    def test_simple_pool_alert_displayed_once_with_full_context(self):
        result = self.simulate(source=('C',), target='G', size='20')
        report = scenario_text(result)
        self.assertIn('ATENÇÃO: Storage Spaces Simple; 1 membro(s)', report)
        self.assertNotIn('OBSERVAÇÃO: Disco 4: pool Simple sem redundância informada.', report)
        self.assertIn('pool Simple sem redundância informada.', result['issues'])
        self.assertIn('DeviceId de membro físico não equivale', report)
        self.assertEqual(result['status'], 'requires_review')
        self.assertFalse(result['approved_for_format'])

    def test_pool_simple_observation_retained_without_correlated_risk(self):
        result = self.simulate(source=('C',), target='G', size='20')
        result['risk_tags'] = []
        report = scenario_text(result)
        self.assertIn('OBSERVAÇÃO: Disco 4: pool Simple sem redundância informada.', report)

    def test_report_C_to_D_20GiB_has_reserve_without_contradictory_message(self):
        result = self.simulate(source=('C',), target='D', size='20')
        self.assertEqual(result['status'], 'requires_review')
        self.assertEqual(result['reserve_bytes'], 10 * GIB)
        self.assertEqual(result['free_bytes_reported'], 90384388096)
        self.assertEqual(
            result['usable_after_reserve_bytes'], 90384388096 - 10 * GIB)
        self.assertGreater(result['usable_after_reserve_bytes'], 20 * GIB)
        text = scenario_text(result)
        self.assertIn('Espaço considerado após reserva:', text)
        self.assertIn('reserva simulada NÃO bloqueia espaço real', text)
        self.assertNotIn('sem reserva de segurança', text)
        self.assertFalse(result['backup_destination_verified'])

    def test_insufficient_C_to_D_80GiB_retains_reserve_calculation(self):
        result = self.simulate(source=('C',), target='D', size='80')
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['usable_after_reserve_bytes'], 90384388096 - 10 * GIB)
        self.assertIn('BLOQUEIO:', scenario_text(result))
        self.assertNotIn('sem reserva de segurança', scenario_text(result))

    def test_unavailable_capacity_never_claims_computed_headroom(self):
        data = snapshot()
        data['volumes'][1]['SizeRemaining'] = None
        result = self.simulate(target='D', data=data)
        self.assertIsNone(result['usable_after_reserve_bytes'])
        self.assertEqual(result['capacity_status'], 'unknown')
        self.assertIn('NÃO IDENTIFICADO', scenario_text(result))

    def test_same_source_and_destination_blocked(self):
        result = self.simulate(source=('G',), target='G')
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any('coincide' in x for x in result['blockers']))
        self.assertIn('BLOQUEIO', scenario_text(result))

    def test_insufficient_space_with_reserve_blocked(self):
        result = self.simulate(source=('C',), target='D', size='80')
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['capacity_status'], 'insufficient_after_reserve')
        self.assertTrue(any('reserva' in x for x in result['blockers']))

    def test_sufficient_raw_space_but_insufficient_after_reserve(self):
        # D has ~84.2 GiB free; 80 GiB is less than free but fails buffer.
        result = self.simulate(target='D', size='80')
        self.assertGreater(result['free_bytes_reported'], result['expected_backup_bytes'])
        self.assertEqual(result['capacity_status'], 'insufficient_after_reserve')

    def test_registered_bootmgr_warning_on_f_without_claiming_bootcurrent(self):
        result = self.simulate(target='F', size='10')
        self.assertEqual(result['status'], 'requires_review')
        self.assertIn('bootmgr_registered', result['risk_tags'])
        self.assertFalse(result['bootcurrent_verified'])
        self.assertIn('BootCurrent', scenario_text(result))

    def test_running_windows_disk_warned_and_no_copy_approval(self):
        result = self.simulate(source=('D',), target='C', size='10')
        self.assertEqual(result['status'], 'requires_review')
        self.assertIn('windows_in_use', result['risk_tags'])
        self.assertFalse(result['approved_for_copy'])

    def test_distinct_disks_no_physical_independence_certification(self):
        result = self.simulate(source=('C','F'), target='D', size='10')
        self.assertEqual(result['source_letters'], ['C', 'F'])
        self.assertFalse(result['physical_independence_verified'])
        self.assertEqual(result['status'], 'requires_review')
        self.assertFalse(result['approved_for_format'])

    def test_zero_or_bad_capacity_remains_blocked(self):
        data = snapshot()
        data['volumes'][-1]['SizeRemaining'] = 0
        result = self.simulate(data=data)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reserve_bytes'], 10 * GIB)

    def test_missing_capacity_requires_review_and_never_approves(self):
        data = snapshot()
        data['volumes'][-1]['SizeRemaining'] = None
        result = self.simulate(data=data)
        self.assertEqual(result['capacity_status'], 'unknown')
        self.assertEqual(result['status'], 'requires_review')
        self.assertFalse(result['approved_for_copy'])

    def test_unknown_drive_rejected_instead_of_fabricated(self):
        with self.assertRaisesRegex(ValueError, 'não consta'):
            self.simulate(source=('Z',))
        with self.assertRaisesRegex(ValueError, 'não consta'):
            self.simulate(target='Z')

    def test_no_disk_report_cannot_be_simulated(self):
        with self.assertRaisesRegex(ValueError, 'diagnóstico'):
            simulate_backup_preflight(None, source_letters=['C'],
                                      target_letter='G', estimate_gib='10')
        with self.assertRaises(ValueError):
            simulate_backup_preflight({}, source_letters=['C'],
                                      target_letter='G', estimate_gib='10')

    def test_no_sources_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Selecione'):
            self.simulate(source=())

    def test_gib_local_decimal_acceptance(self):
        self.assertEqual(parse_gib('1,5'), int(1.5 * GIB))
        self.assertEqual(parse_gib('20.25'), int(20.25 * GIB))
        self.assertEqual(parse_gib('0.001'), 1073742)

    def test_invalid_gib_rejected(self):
        for bad in ('', '0', '-2', '1e3', '1,2345', 'abc', 'NaN', 'Infinity',
                    '1 GiB', '1_000', '10,00,0', '999999999', None, 20):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                parse_gib(bad)

    def test_snapshot_not_modified_and_no_operating_system_calls(self):
        data = snapshot()
        before = repr(data)
        result = self.simulate(data=data)
        self.assertEqual(repr(data), before)
        self.assertTrue(result['preview_only'])
        self.assertFalse(result['backup_integrity_verified'])


if __name__ == '__main__':
    unittest.main()
