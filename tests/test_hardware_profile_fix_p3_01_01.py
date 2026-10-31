"""FIX-P3-01-01: ressalvas da revisão da PR #113 (perfil de hardware).

Só dados simulados: nenhum comando real (PowerShell, WMI) é executado.
"""
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import hardware_profile as hp
import optimization_engine as oe

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def _base(**extra):
    hardware = {
        'cpu': {'Name': 'AMD Ryzen 5 5600', 'NumberOfCores': 6, 'NumberOfLogicalProcessors': 12},
        'gpu': [{'Name': 'NVIDIA GeForce RTX 3060'}],
        'ram': [{'Capacity': 8 * GIB, 'ConfiguredClockSpeed': 3200}] * 2,
        'os': {'Caption': 'Microsoft Windows 11 Pro', 'Version': '10.0.22631'},
    }
    hardware.update(extra)
    return hardware


class SameChannelTests(unittest.TestCase):
    def _dual(self, *labels):
        return hp._dual_channel([dict(Capacity=8 * GIB, **item) for item in labels])

    def test_all_in_same_channel_is_not_confirmed(self):
        cases = (
            (dict(BankLabel='Channel A'), dict(BankLabel='Channel A')),
            (dict(DeviceLocator='ChannelA-DIMM0'), dict(DeviceLocator='ChannelA-DIMM1')),
        )
        for labels in cases:
            with self.subTest(labels=labels):
                self.assertEqual(self._dual(*labels), 'não confirmado (módulos no mesmo canal)')

    def test_one_without_channel_stays_probable(self):
        self.assertEqual(self._dual(dict(DeviceLocator='ChannelA-DIMM0'), dict(DeviceLocator='DIMM 1')),
                         'provável (não confirmado)')

    def test_two_channels_confirmed(self):
        self.assertEqual(self._dual(dict(BankLabel='Channel A'), dict(BankLabel='Channel B')),
                         'sim (confirmado)')

    def test_same_channel_shown_on_screen(self):
        hardware = _base(ram=[{'Capacity': 8 * GIB, 'DeviceLocator': 'ChannelA-DIMM0'},
                              {'Capacity': 8 * GIB, 'DeviceLocator': 'ChannelA-DIMM1'}])
        text = '\n'.join(hp.profile_lines(hp.build_profile(hardware)))
        self.assertIn('dual channel: não confirmado (módulos no mesmo canal)', text)


class MissingBusTypeTests(unittest.TestCase):
    def test_new_bus_types_are_external_never_ssd(self):
        cases = ((4, '1394'), (6, 'Fibre Channel'), (9, 'iSCSI'), (14, 'virtual'),
                 ('1394', '1394'), ('Fibre Channel', 'Fibre Channel'), ('fibre  channel', 'Fibre Channel'),
                 ('iSCSI', 'iSCSI'), ('ISCSI', 'iSCSI'), ('Virtual', 'virtual'))
        for bus, name in cases:
            for media in (4, 3, 'SSD', None):
                with self.subTest(bus=bus, media=media):
                    disks = hp._disks({'disks': [{'BusType': bus, 'MediaType': media, 'Size': 100 * GIB}]})
                    self.assertEqual(disks[0]['bus'], name)
                    self.assertEqual(disks[0]['type'], hp.DISK_EXTERNAL)
                    self.assertNotIn(disks[0]['type'], (hp.DISK_SSD, hp.DISK_NVME, hp.DISK_HDD))

    def test_new_buses_in_external_set(self):
        for name in ('1394', 'Fibre Channel', 'iSCSI', 'virtual'):
            self.assertIn(name, hp._EXTERNAL_BUSES)


class BatteryOnlyNotebookTests(unittest.TestCase):
    WARNING = ('Aviso: só a bateria indicou notebook; se este é um PC de mesa com nobreak (UPS) '
               'ligado por USB, o app o trata como notebook por cuidado.')

    def _profile(self, **extra):
        return hp.build_profile(_base(**extra))

    def test_only_battery_shows_warning(self):
        profile = self._profile(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [3]},
                                battery=[{'BatteryStatus': 2}])
        self.assertEqual(profile['form_factor'], 'notebook')
        self.assertIs(profile['battery_only_notebook'], True)
        self.assertIn('  ' + self.WARNING, hp.profile_lines(profile))

    def test_only_battery_without_chassis(self):
        profile = self._profile(pc={'PCSystemType': 1}, battery={'BatteryStatus': 2})
        self.assertIs(profile['battery_only_notebook'], True)

    def test_other_evidence_no_warning(self):
        cases = (
            dict(pc={'PCSystemType': 2}, chassis={'ChassisTypes': [3]}, battery={'BatteryStatus': 2}),
            dict(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [10]}, battery={'BatteryStatus': 2}),
            dict(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [3]}, battery=None),
            dict(pc={'PCSystemType': 2}, battery=None),
        )
        for extra in cases:
            with self.subTest(extra=extra):
                profile = self._profile(**extra)
                self.assertIs(profile['battery_only_notebook'], False)
                text = '\n'.join(hp.profile_lines(profile))
                self.assertNotIn('nobreak', text)

    def test_helper_on_malformed_input(self):
        for hardware in ({}, {'pc': 'x', 'battery': 'x'}, {'chassis': None}):
            with self.subTest(hardware=hardware):
                self.assertIs(hp._notebook_by_battery_only(hardware), False)

    def test_old_profile_without_key_has_no_warning(self):
        profile = self._profile(pc={'PCSystemType': 1}, battery={'BatteryStatus': 2})
        profile.pop('battery_only_notebook')
        self.assertNotIn('nobreak', '\n'.join(hp.profile_lines(profile)))


class ErrorTextTests(unittest.TestCase):
    """R-07: erro do PowerShell não sai cru (pode trazer caminho com nome do usuário)."""

    def _inspect(self, power_error=True):
        secret = 'Falhou em C:\\Users\\fulano\\x'

        def fake_ps(code, timeout=22):
            raise oe.OptimizationError(secret)

        def boom(*args, **kwargs):
            raise AssertionError('comando real executado')

        power = mock.patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError(secret)) \
            if power_error else mock.patch.object(oe, 'available_power_plans', return_value=[])
        with mock.patch.object(oe, '_is_windows', return_value=True), mock.patch.object(oe, '_ps', fake_ps), \
                mock.patch.object(oe, '_run', boom), mock.patch.object(subprocess, 'run', boom), \
                power, mock.patch.object(oe, 'active_power_guid', return_value=None):
            return oe.inspect_pc()

    def test_errors_have_no_user_or_path(self):
        report = self._inspect()
        joined = '\n'.join(report['errors'])
        self.assertNotIn('fulano', joined)
        self.assertNotIn('C:\\', joined)
        self.assertIn('Inventário disks: não foi possível ler.', report['errors'])
        self.assertIn('Energia: não foi possível ler os planos de energia.', report['errors'])

    def test_every_inventory_error_is_generic(self):
        report = self._inspect(power_error=False)
        inventory = [e for e in report['errors'] if e.startswith('Inventário ')]
        self.assertTrue(inventory)
        for error in inventory:
            self.assertRegex(error, r'^Inventário [a-z]+: não foi possível ler\.$')


class IsWindowsTests(unittest.TestCase):
    def test_helper_follows_os_name(self):
        self.assertEqual(oe._is_windows(), oe.os.name == 'nt')

    def test_run_refuses_outside_windows(self):
        with mock.patch.object(oe, '_is_windows', return_value=False), \
                mock.patch.object(subprocess, 'run', side_effect=AssertionError('não rodar')):
            with self.assertRaises(oe.OptimizationError):
                oe._run(['powershell', '-Command', 'x'])

    def test_inspect_outside_windows_runs_nothing(self):
        def boom(*args, **kwargs):
            raise AssertionError('comando executado')
        with mock.patch.object(oe, '_is_windows', return_value=False), mock.patch.object(oe, '_ps', boom), \
                mock.patch.object(oe, '_run', boom):
            report = oe.inspect_pc()
        self.assertIs(report['windows'], False)

    def test_engine_no_longer_reads_os_name_directly(self):
        source = (ROOT / 'optimization_engine.py').read_text(encoding='utf-8')
        self.assertEqual(source.count("os.name"), 1, 'só _is_windows() lê os.name')


class NoGlobalPatchTests(unittest.TestCase):
    """Os testes do perfil de hardware não trocam os.name nem threading.Thread do processo todo."""

    FILES = ('test_hardware_profile_p3_01.py', 'test_hardware_profile_p3_01_fatia2.py',
             'test_hardware_profile_fix_p3_01_01.py')
    PATTERN = re.compile(r"patch(?:\.object)?\([^)\n]*(?:os,\s*'name'|os\.name|threading,\s*'Thread'|threading\.Thread)")

    def test_no_global_patches(self):
        for name in self.FILES:
            with self.subTest(file=name):
                text = (ROOT / 'tests' / name).read_text(encoding='utf-8')
                self.assertIsNone(self.PATTERN.search(text))


if __name__ == '__main__':
    unittest.main()
