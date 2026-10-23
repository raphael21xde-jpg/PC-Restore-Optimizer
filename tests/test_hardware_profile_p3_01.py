"""P3-01 fatia 1: perfil de hardware a partir do inventário já lido (dados simulados)."""
import ast
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import hardware_profile as hp

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def _hw(cpu=None, gpus=(), ram=(), pc_type=None, os_info=None):
    hardware = {}
    if cpu is not None:
        hardware['cpu'] = cpu
    hardware['gpu'] = [{'Name': name, 'DriverVersion': '1.0'} for name in gpus]
    hardware['ram'] = [{'Capacity': gib * GIB, 'Speed': 3200, 'ConfiguredClockSpeed': mts,
                        'Manufacturer': 'X'} for gib, mts in ram]
    if pc_type is not None:
        hardware['pc'] = {'Manufacturer': 'Fab', 'Model': 'Mod', 'PCSystemType': pc_type}
    hardware['os'] = os_info or {'Caption': 'Microsoft Windows 11 Pro', 'Version': '10.0.22631',
                                 'BuildNumber': '22631'}
    return hardware


FIXTURES = {
    'notebook_fraco': (_hw({'Name': 'Intel Celeron N4020', 'NumberOfCores': 2, 'NumberOfLogicalProcessors': 2},
                           ['Intel(R) UHD Graphics 600'], [(4, 2400)], pc_type=2), 'notebook'),
    'escritorio': (_hw({'Name': 'Intel Core i3-10100', 'NumberOfCores': 4, 'NumberOfLogicalProcessors': 8},
                       ['Intel(R) UHD Graphics 630'], [(4, 2666), (4, 2666)], pc_type=1), 'intermediario'),
    'gamer': (_hw({'Name': 'AMD Ryzen 5 5600', 'NumberOfCores': 6, 'NumberOfLogicalProcessors': 12},
                  ['NVIDIA GeForce RTX 3060'], [(8, 3200), (8, 3200)], pc_type=1), 'gamer'),
    'workstation': (_hw({'Name': 'AMD Ryzen 9 7950X', 'NumberOfCores': 16, 'NumberOfLogicalProcessors': 32},
                        ['AMD Radeon RX 7900 XTX'], [(16, 6000), (16, 6000)], pc_type=3), 'alto_desempenho'),
    'sem_dados': ({}, 'indefinido'),
}


class ClassificationTests(unittest.TestCase):
    def test_five_fixture_pcs(self):
        for name, (hardware, tier) in FIXTURES.items():
            with self.subTest(pc=name):
                profile = hp.build_profile(hardware)
                self.assertEqual(profile['tier'], tier)
                self.assertTrue(profile['reasons'])
                self.assertTrue(all(isinstance(r, str) and r for r in profile['reasons']))

    def test_basic_desktop(self):
        hardware = _hw({'Name': 'Old', 'NumberOfCores': 2, 'NumberOfLogicalProcessors': 4},
                       [], [(4, 1600)], pc_type=1)
        self.assertEqual(hp.build_profile(hardware)['tier'], 'basico')

    def test_notebook_with_rtx_stays_notebook(self):
        hardware = _hw({'Name': 'Intel Core i7-12700H', 'NumberOfCores': 14, 'NumberOfLogicalProcessors': 20},
                       ['NVIDIA GeForce RTX 3070 Laptop GPU'], [(16, 3200), (16, 3200)], pc_type=2)
        profile = hp.build_profile(hardware)
        self.assertEqual(profile['form_factor'], 'notebook')
        self.assertEqual(profile['tier'], 'notebook')

    def test_missing_pc_system_type_is_unknown_never_desktop(self):
        hardware = FIXTURES['gamer'][0].copy()
        hardware.pop('pc')
        profile = hp.build_profile(hardware)
        self.assertEqual(profile['form_factor'], 'desconhecido')
        self.assertIn('form_factor', profile['unknown'])

    def test_missing_cpu_or_ram_is_undefined(self):
        no_cpu = FIXTURES['gamer'][0].copy(); no_cpu.pop('cpu')
        no_ram = FIXTURES['gamer'][0].copy(); no_ram['ram'] = []
        bad_cpu = FIXTURES['gamer'][0].copy()
        bad_cpu['cpu'] = {'Name': 'x', 'NumberOfCores': 'seis', 'NumberOfLogicalProcessors': True}
        for hardware in (no_cpu, no_ram, bad_cpu):
            with self.subTest(hardware=sorted(hardware)):
                self.assertEqual(hp.build_profile(hardware)['tier'], 'indefinido')

    def test_garbage_inputs_never_raise(self):
        garbage = [None, 'texto', 42, [], [1, 2], {'cpu': 'x'}, {'cpu': [None, 'a', {}]},
                   {'ram': {'Capacity': -5}}, {'ram': [{'Capacity': True}, 'x', None]},
                   {'gpu': {'Name': {'a': 1}}}, {'gpu': 'NVIDIA'}, {'pc': {'PCSystemType': [2]}},
                   {'os': ['a', None]}, {'cpu': {'NumberOfCores': -4, 'NumberOfLogicalProcessors': float('nan')}},
                   {'ram': [{'Capacity': float('inf'), 'ConfiguredClockSpeed': -1}]}]
        for item in garbage:
            with self.subTest(item=repr(item)):
                profile = hp.build_profile(item)
                self.assertEqual(profile['tier'], 'indefinido')
                json.dumps(profile)
                self.assertTrue(hp.profile_lines(profile))
        for item in (None, 'x', [], {'tier': 5, 'cpu': 'x', 'gpus': 'y', 'ram': None}):
            self.assertTrue(hp.profile_lines(item))

    def test_classify_returns_tier_and_reasons(self):
        profile = hp.build_profile(FIXTURES['gamer'][0])
        tier, reasons = hp.classify(profile)
        self.assertEqual(tier, 'gamer')
        self.assertTrue(reasons)


class DedicatedGpuTests(unittest.TestCase):
    def test_positive(self):
        for name in ('NVIDIA GeForce RTX 4090', 'NVIDIA GeForce GTX 1650', 'NVIDIA Quadro P2000',
                     'NVIDIA RTX A4000', 'AMD Radeon RX 6600', 'AMD Radeon Pro W6800',
                     'Intel(R) Arc(TM) A770 Graphics', 'Intel Arc B580'):
            with self.subTest(name=name):
                self.assertIs(hp.is_dedicated_gpu(name), True)

    def test_negative(self):
        for name in ('Microsoft Basic Display Adapter', 'Intel(R) UHD Graphics 770',
                     'Intel(R) Iris(R) Xe Graphics', 'AMD Radeon(TM) Vega 8 Graphics', '', '   '):
            with self.subTest(name=name):
                self.assertIs(hp.is_dedicated_gpu(name), False)

    def test_unknown(self):
        for name in ('Placa Misteriosa 3000', None, 5, {'Name': 'RTX'}):
            with self.subTest(name=name):
                self.assertIsNone(hp.is_dedicated_gpu(name))

    def test_basic_display_adapter_never_dedicated(self):
        self.assertIs(hp.is_dedicated_gpu('Microsoft Basic Display Adapter (RTX)'), False)
        hardware = _hw({'Name': 'c', 'NumberOfCores': 8, 'NumberOfLogicalProcessors': 16},
                       ['Microsoft Basic Display Adapter'], [(16, 3200), (16, 3200)], pc_type=1)
        self.assertNotIn(hp.build_profile(hardware)['tier'], ('gamer', 'alto_desempenho'))


class DualChannelTests(unittest.TestCase):
    def _dual(self, ram):
        hardware = _hw({'Name': 'c', 'NumberOfCores': 4, 'NumberOfLogicalProcessors': 8}, [], ram, pc_type=1)
        return hp.build_profile(hardware)['ram']['dual_channel']

    def test_texts(self):
        self.assertEqual(self._dual([(8, 3200)]), 'não (1 módulo)')
        self.assertEqual(self._dual([(8, 3200), (8, 3200)]), 'provável (não confirmado)')
        different = self._dual([(8, 3200), (4, 3200)])
        self.assertIn('não confirmado', different)

    def test_never_confirmed_without_negation(self):
        for ram in ([(8, 1)], [(8, 1), (8, 1)], [(8, 1), (16, 1)], [(8, 1)] * 4, []):
            text = self._dual(ram)
            if 'confirmado' in text:
                self.assertIn('não', text)

    def test_total_and_speed(self):
        hardware = FIXTURES['gamer'][0]
        ram = hp.build_profile(hardware)['ram']
        self.assertEqual(ram['total_gib'], 16)
        self.assertEqual(ram['configured_mts'], 3200)
        self.assertEqual(ram['modules'], 2)


class ReadOnlyTests(unittest.TestCase):
    def test_no_process_execution(self):
        def boom(*args, **kwargs):
            raise AssertionError('comando executado')
        with mock.patch.object(subprocess, 'run', boom), mock.patch.object(subprocess, 'Popen', boom), \
                mock.patch.object(os, 'system', boom):
            for hardware, _tier in FIXTURES.values():
                hp.profile_lines(hp.build_profile(hardware))

    def test_module_imports_no_system_access(self):
        tree = ast.parse((ROOT / 'hardware_profile.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        for forbidden in ('subprocess', 'ctypes', 'winreg', 'tkinter', 'os'):
            self.assertNotIn(forbidden, imported)


class PrivacyTests(unittest.TestCase):
    def test_no_personal_data(self):
        hardware = _hw({'Name': 'AMD Ryzen 5 5600', 'NumberOfCores': 6, 'NumberOfLogicalProcessors': 12,
                        'SystemName': 'PC-DO-FULANO', 'SerialNumber': 'SN-ABC-123'},
                       ['NVIDIA GeForce RTX 3060'], [(8, 3200), (8, 3200)], pc_type=1)
        hardware['ram'][0]['SerialNumber'] = 'SN-RAM-999'
        hardware['pc']['Name'] = 'PC-DO-FULANO'
        hardware['pc']['UserName'] = 'FULANO\\fulano'
        hardware['board'] = {'Manufacturer': 'PlacaX', 'Product': 'B550', 'SerialNumber': 'SN-BOARD-1'}
        hardware['bios'] = {'Manufacturer': 'BiosX', 'SMBIOSBIOSVersion': 'F42'}
        hardware['os']['Caption'] = 'C:\\Users\\fulano\\Desktop'
        hardware['gpu'].append({'Name': 'C:\\Users\\fulano\\gpu.exe'})
        profile = hp.build_profile(hardware)
        dump = json.dumps(profile, ensure_ascii=False) + '\n'.join(hp.profile_lines(profile))
        for secret in ('SN-ABC-123', 'SN-RAM-999', 'SN-BOARD-1', 'PC-DO-FULANO', 'fulano', 'Users',
                       'PlacaX', 'B550', 'BiosX', 'F42'):
            self.assertNotIn(secret, dump)
        self.assertEqual(profile['tier'], 'gamer')


class EngineIntegrationTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'cenário fora do Windows')
    def test_inspect_pc_outside_windows(self):
        import optimization_engine as oe
        def boom(*args, **kwargs):
            raise AssertionError('comando executado')
        with mock.patch.object(oe, '_ps', boom), mock.patch.object(oe, '_run', boom), \
                mock.patch.object(subprocess, 'run', boom):
            report = oe.inspect_pc()
        self.assertEqual(report['profile']['tier'], 'indefinido')
        json.dumps(report, ensure_ascii=False)

    @unittest.skipUnless(os.name == 'nt', 'só no Windows')
    def test_inspect_pc_on_windows_simulated(self):
        import optimization_engine as oe
        hardware = FIXTURES['gamer'][0]
        def fake_ps(code, timeout=22):
            for key, cim in (('cpu', 'Win32_Processor'), ('gpu', 'Win32_VideoController'),
                             ('ram', 'Win32_PhysicalMemory'), ('os', 'Win32_OperatingSystem'),
                             ('pc', 'Win32_ComputerSystem')):
                if cim in code:
                    return hardware[key]
            return {}
        with mock.patch.object(oe, '_ps', fake_ps), \
                mock.patch.object(oe, 'available_power_plans', return_value=[]), \
                mock.patch.object(oe, 'active_power_guid', return_value=None):
            report = oe.inspect_pc()
        self.assertEqual(report['profile']['tier'], 'gamer')
        self.assertEqual(report['profile']['form_factor'], 'desktop')


class UiWiringTests(unittest.TestCase):
    def test_scan_finished_calls_profile_lines(self):
        tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == '_scan_finished':
                found = any(isinstance(call, ast.Call) and getattr(call.func, 'id', None) == 'profile_lines'
                            for call in ast.walk(node))
        self.assertTrue(found)


if __name__ == '__main__':
    unittest.main()
