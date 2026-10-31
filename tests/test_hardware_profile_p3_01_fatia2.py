"""P3-01 fatia 2: discos, gabinete/bateria, dual channel confirmado e confirmação
antes da análise. Só dados simulados: nenhum comando real é executado."""
import ast
import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import hardware_profile as hp
from tk_helpers import track_tk_root

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3
WRITE_VERBS = re.compile(r'\b(Set|Remove|Format|Clear|New|Initialize)-', re.I)


def _base(**extra):
    hardware = {
        'cpu': {'Name': 'AMD Ryzen 5 5600', 'NumberOfCores': 6, 'NumberOfLogicalProcessors': 12},
        'gpu': [{'Name': 'NVIDIA GeForce RTX 3060'}],
        'ram': [{'Capacity': 8 * GIB, 'ConfiguredClockSpeed': 3200}] * 2,
        'os': {'Caption': 'Microsoft Windows 11 Pro', 'Version': '10.0.22631'},
    }
    hardware.update(extra)
    return hardware


class DiskTests(unittest.TestCase):
    def _types(self, rows):
        return [d['type'] for d in hp._disks({'disks': rows})]

    def test_nvme_by_bus_number_or_text(self):
        self.assertEqual(self._types([{'MediaType': 4, 'BusType': 17, 'Size': 1000 * GIB},
                                      {'MediaType': 'SSD', 'BusType': 'NVMe', 'Size': 500 * GIB},
                                      {'MediaType': 0, 'BusType': 17}]), ['NVMe'] * 3)

    def test_ssd_and_hdd(self):
        self.assertEqual(self._types([{'MediaType': 4, 'BusType': 11}, {'MediaType': 'SSD', 'BusType': 'SATA'},
                                      {'MediaType': 3, 'BusType': 11}, {'MediaType': 'HDD', 'BusType': 'SATA'}]),
                         ['SSD', 'SSD', 'HDD', 'HDD'])

    def test_external_or_virtual(self):
        rows = [{'MediaType': 4, 'BusType': 7}, {'MediaType': 3, 'BusType': 'USB'},
                {'MediaType': 0, 'BusType': 16}, {'MediaType': 4, 'BusType': 'Storage Spaces'},
                {'MediaType': 0, 'BusType': 'Spaces'}]
        self.assertEqual(self._types(rows), ['externo/virtual'] * 5)

    def test_anything_else_is_unknown_never_ssd(self):
        rows = [{'MediaType': 0, 'BusType': 11}, {'MediaType': 'Unspecified', 'BusType': 'SATA'},
                {'MediaType': 5, 'BusType': 8}, {'MediaType': 'SCM'}, {}]
        self.assertEqual(self._types(rows), ['desconhecido'] * 5)

    def test_malformed_values_never_raise(self):
        bad = [None, 'texto', True, False, float('nan'), float('inf'), -3, 3.5, [4], {'x': 4}]
        for value in bad:
            with self.subTest(value=repr(value)):
                disks = hp._disks({'disks': [{'MediaType': value, 'BusType': value, 'Size': value}]})
                self.assertEqual(disks, [{'type': 'desconhecido', 'bus': None, 'size_gib': None}])
        for disks in (None, 'x', 5, True, [None, 'a', 3], {'MediaType': 'x'}):
            with self.subTest(disks=repr(disks)):
                result = hp._disks({'disks': disks})
                self.assertIsInstance(result, list)
                self.assertTrue(all(d['type'] == 'desconhecido' for d in result))
        self.assertEqual(hp._disks(None), [])
        self.assertEqual(hp._disks('x'), [])

    def test_size_in_gib(self):
        disk = hp._disks({'disks': {'MediaType': 4, 'BusType': 17, 'Size': 1000204886016}})[0]
        self.assertEqual(disk, {'type': 'NVMe', 'bus': 'NVMe', 'size_gib': 931.5})

    def test_profile_includes_disks_and_lines(self):
        profile = hp.build_profile(_base(disks=[{'MediaType': 4, 'BusType': 17, 'Size': 500 * GIB},
                                                {'MediaType': 3, 'BusType': 11, 'Size': 2000 * GIB}]))
        self.assertEqual([d['type'] for d in profile['disks']], ['NVMe', 'HDD'])
        self.assertNotIn('disks', profile['unknown'])
        text = '\n'.join(hp.profile_lines(profile))
        self.assertIn('Disco: NVMe', text)
        self.assertIn('2000 GiB', text)
        self.assertIn('HD (disco mecânico)', text)

    def test_no_disks_marks_unknown(self):
        for hardware in (_base(), _base(disks=None), _base(disks=[])):
            profile = hp.build_profile(hardware)
            self.assertEqual(profile['disks'], [])
            self.assertIn('disks', profile['unknown'])
            self.assertIn('Discos: não disponível', '\n'.join(hp.profile_lines(profile)))


class FormFactorTests(unittest.TestCase):
    def _form(self, **extra):
        return hp.build_profile(_base(**extra))['form_factor']

    def test_notebook_by_system_type(self):
        self.assertEqual(self._form(pc={'PCSystemType': 2}), 'notebook')

    def test_notebook_by_chassis(self):
        for code in (8, 9, 10, 14, 30, 31, 32):
            with self.subTest(code=code):
                self.assertEqual(self._form(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [code]},
                                            battery=None), 'notebook')

    def test_notebook_by_battery(self):
        for battery in ({'BatteryStatus': 2}, [{'BatteryStatus': 1}]):
            with self.subTest(battery=battery):
                self.assertEqual(self._form(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [3]},
                                            battery=battery), 'notebook')

    def test_desktop_needs_type_chassis_and_no_battery(self):
        for kind in (1, 3):
            for code in (3, 4, 5, 6, 7, 15, 16, 35, 36):
                with self.subTest(kind=kind, code=code):
                    self.assertEqual(self._form(pc={'PCSystemType': kind}, chassis=[{'ChassisTypes': [code]}],
                                                battery=None), 'desktop')
        self.assertEqual(self._form(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [3]}, battery=[]), 'desktop')

    def test_desktop_without_full_proof_is_unknown(self):
        cases = {
            'só PCSystemType': dict(pc={'PCSystemType': 1}),
            'sem consulta de bateria': dict(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [3]}),
            'sem gabinete': dict(pc={'PCSystemType': 1}, battery=None),
            'gabinete outro': dict(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [2]}, battery=None),
            'gabinete misto': dict(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [3, 2]}, battery=None),
            'sem PCSystemType': dict(chassis={'ChassisTypes': [3]}, battery=None),
            'PCSystemType 4': dict(pc={'PCSystemType': 4}, chassis={'ChassisTypes': [3]}, battery=None),
            'bateria estranha': dict(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [3]}, battery='x'),
        }
        for name, extra in cases.items():
            with self.subTest(caso=name):
                profile = hp.build_profile(_base(**extra))
                self.assertEqual(profile['form_factor'], 'desconhecido')
                self.assertIn('form_factor', profile['unknown'])

    def test_malformed_chassis_never_raise(self):
        for chassis in (None, 'x', 5, [None], {'ChassisTypes': 'Desktop'}, {'ChassisTypes': [True, -1, 3.5]},
                        {'ChassisTypes': float('nan')}):
            with self.subTest(chassis=repr(chassis)):
                self.assertEqual(self._form(pc={'PCSystemType': 1}, chassis=chassis, battery=None), 'desconhecido')

    def test_notebook_tier_from_chassis(self):
        profile = hp.build_profile(_base(pc={'PCSystemType': 1}, chassis={'ChassisTypes': [10]}, battery=None))
        self.assertEqual(profile['tier'], 'notebook')


class DualChannelTests(unittest.TestCase):
    def _dual(self, modules):
        return hp._dual_channel([dict(Capacity=gib * GIB, **labels) for gib, labels in modules])

    def test_confirmed_with_explicit_channels(self):
        for a, b in ((dict(DeviceLocator='ChannelA-DIMM0'), dict(DeviceLocator='ChannelB-DIMM0')),
                     (dict(BankLabel='P0 CHANNEL A'), dict(BankLabel='P0 CHANNEL B')),
                     (dict(DeviceLocator='DIMM 0', BankLabel='Channel A'), dict(DeviceLocator='DIMM 1', BankLabel='Channel B'))):
            with self.subTest(a=a, b=b):
                self.assertEqual(self._dual([(8, a), (8, b)]), 'sim (confirmado)')
        four = [(16, dict(DeviceLocator=f'Channel{c}-DIMM{i}')) for c in 'AB' for i in (0, 1)]
        self.assertEqual(self._dual(four), 'sim (confirmado)')

    def test_bank_or_dimm_labels_stay_probable(self):
        for a, b in ((dict(BankLabel='BANK 0'), dict(BankLabel='BANK 1')),
                     (dict(DeviceLocator='DIMM 1'), dict(DeviceLocator='DIMM 2')),
                     ({}, {}), (dict(DeviceLocator=5), dict(BankLabel=None))):
            with self.subTest(a=a, b=b):
                self.assertEqual(self._dual([(8, a), (8, b)]), 'provável (não confirmado)')

    def test_same_channel_does_not_confirm(self):
        self.assertEqual(self._dual([(8, dict(DeviceLocator='ChannelA-DIMM0')),
                                     (8, dict(DeviceLocator='ChannelA-DIMM1'))]),
                         'não confirmado (módulos no mesmo canal)')

    def test_one_module_and_different_sizes(self):
        self.assertEqual(self._dual([(8, dict(DeviceLocator='ChannelA-DIMM0'))]), 'não (1 módulo)')
        self.assertIn('não confirmado', self._dual([(8, dict(DeviceLocator='ChannelA-DIMM0')),
                                                    (16, dict(DeviceLocator='ChannelB-DIMM0'))]))

    def test_partial_labels_do_not_confirm(self):
        self.assertEqual(self._dual([(8, dict(DeviceLocator='ChannelA-DIMM0')), (8, dict(DeviceLocator='ChannelB-DIMM0')),
                                     (8, dict(DeviceLocator='DIMM 3'))]), 'provável (não confirmado)')

    def test_malformed_never_raise(self):
        for entries in (None, 'x', [], [None], [{'Capacity': 'x'}], {'Capacity': 8 * GIB}):
            with self.subTest(entries=repr(entries)):
                self.assertIsInstance(hp._dual_channel(entries), str)

    def test_called_from_ram(self):
        hardware = _base(ram=[{'Capacity': 8 * GIB, 'DeviceLocator': 'ChannelA-DIMM0'},
                              {'Capacity': 8 * GIB, 'DeviceLocator': 'ChannelB-DIMM0'}])
        self.assertEqual(hp.build_profile(hardware)['ram']['dual_channel'], 'sim (confirmado)')
        with mock.patch.object(hp, '_dual_channel', return_value='marcador') as dual:
            self.assertEqual(hp._ram(hardware)['dual_channel'], 'marcador')
        dual.assert_called_once()


class ConfirmationTextTests(unittest.TestCase):
    def test_text_mentions_what_is_read_and_read_only(self):
        text = hp.SCAN_CONFIRMATION.lower()
        for word in ('processador', 'memória', 'placa de vídeo', 'discos', 'gabinete', 'bateria',
                     'windows', 'só leitura', 'nada é alterado'):
            self.assertIn(word, text)


class PrivacyTests(unittest.TestCase):
    def test_profile_has_no_serial_name_or_path(self):
        hardware = _base(
            pc={'PCSystemType': 1, 'Name': 'PC-DO-FULANO'},
            chassis={'ChassisTypes': [3], 'SerialNumber': 'SN-CHASSI-1'},
            battery=None,
            disks=[{'MediaType': 4, 'BusType': 17, 'Size': 500 * GIB, 'SerialNumber': 'SN-DISK-77',
                    'FriendlyName': 'Samsung SSD 980 PRO', 'DeviceId': 'C:\\Users\\fulano'},
                   {'MediaType': 'C:\\Users\\fulano', 'BusType': '\\\\servidor\\x', 'Size': 1}],
            ram=[{'Capacity': 8 * GIB, 'DeviceLocator': 'ChannelA C:\\Users\\fulano', 'SerialNumber': 'SN-RAM-5'},
                 {'Capacity': 8 * GIB, 'DeviceLocator': 'ChannelB-DIMM0'}])
        profile = hp.build_profile(hardware)
        dump = json.dumps(profile, ensure_ascii=False) + '\n'.join(hp.profile_lines(profile))
        for secret in ('SN-CHASSI-1', 'SN-DISK-77', 'Samsung', '980 PRO', 'SN-RAM-5', 'fulano', 'Users',
                       'servidor', 'PC-DO-FULANO', 'DeviceLocator', 'ChannelA'):
            self.assertNotIn(secret, dump)
        for disk in profile['disks']:
            self.assertEqual(set(disk), {'type', 'bus', 'size_gib'})


class EngineTests(unittest.TestCase):
    def _run_simulated(self):
        import optimization_engine as oe
        calls = []
        answers = {
            'Win32_Processor': {'Name': 'AMD Ryzen 5 5600', 'NumberOfCores': 6, 'NumberOfLogicalProcessors': 12},
            'Win32_VideoController': [{'Name': 'NVIDIA GeForce RTX 3060', 'DriverVersion': '1'}],
            'Win32_PhysicalMemory': [{'Capacity': 8 * GIB, 'ConfiguredClockSpeed': 3200, 'DeviceLocator': 'ChannelA-DIMM0'},
                                     {'Capacity': 8 * GIB, 'ConfiguredClockSpeed': 3200, 'DeviceLocator': 'ChannelB-DIMM0'}],
            'Win32_OperatingSystem': {'Caption': 'Microsoft Windows 11 Pro', 'Version': '10.0.22631'},
            'Win32_ComputerSystem': {'PCSystemType': 1},
            'Win32_SystemEnclosure': {'ChassisTypes': [3]},
            'Win32_Battery': None,
            'Get-PhysicalDisk': [{'MediaType': 4, 'BusType': 17, 'Size': 1000 * GIB}],
        }

        def fake_ps(code, timeout=22):
            calls.append(code)
            for marker, answer in answers.items():
                if marker in code:
                    return answer
            return None

        def boom(*args, **kwargs):
            raise AssertionError('comando real executado')

        with mock.patch.object(oe, '_is_windows', return_value=True), mock.patch.object(oe, '_ps', fake_ps), \
                mock.patch.object(oe, '_run', boom), mock.patch.object(subprocess, 'run', boom), \
                mock.patch.object(subprocess, 'Popen', boom), \
                mock.patch.object(oe, 'available_power_plans', return_value=[]), \
                mock.patch.object(oe, 'active_power_guid', return_value=None):
            report = oe.inspect_pc()
        return report, calls

    def test_new_queries_and_profile(self):
        report, calls = self._run_simulated()
        joined = '\n'.join(calls)
        self.assertIn('Win32_SystemEnclosure', joined)
        self.assertIn('ChassisTypes', joined)
        self.assertIn('Win32_Battery', joined)
        self.assertIn('Get-PhysicalDisk', joined)
        ram_query = next(c for c in calls if 'Win32_PhysicalMemory' in c)
        self.assertIn('DeviceLocator', ram_query)
        self.assertIn('BankLabel', ram_query)
        profile = report['profile']
        self.assertEqual(profile['form_factor'], 'desktop')
        self.assertEqual(profile['ram']['dual_channel'], 'sim (confirmado)')
        self.assertEqual(profile['disks'][0]['type'], 'NVMe')
        json.dumps(report, ensure_ascii=False)

    def test_queries_are_read_only_and_private(self):
        _report, calls = self._run_simulated()
        self.assertTrue(calls)
        for code in calls:
            with self.subTest(code=code):
                self.assertNotIn('serialnumber', code.lower())
                self.assertNotIn('friendlyname', code.lower())
                self.assertIsNone(WRITE_VERBS.search(code))

    def test_does_not_use_disk_inventory(self):
        import diagnostics
        import optimization_engine as oe
        with mock.patch.object(diagnostics, 'disk_inventory', side_effect=AssertionError('não usar')):
            self._run_simulated()
        self.assertNotIn('disk_inventory', (ROOT / 'optimization_engine.py').read_text(encoding='utf-8'))
        self.assertTrue(oe)

    def test_outside_windows_runs_no_command(self):
        import optimization_engine as oe

        def boom(*args, **kwargs):
            raise AssertionError('comando executado')
        with mock.patch.object(oe, '_is_windows', return_value=False), mock.patch.object(oe, '_ps', boom), \
                mock.patch.object(oe, '_run', boom), mock.patch.object(subprocess, 'run', boom):
            report = oe.inspect_pc()
        self.assertIn('disks', report['profile']['unknown'])
        self.assertEqual(report['profile']['disks'], [])


class ScanSourceTests(unittest.TestCase):
    """Sem Tk: confere no código que scan() pergunta antes de chamar inspect_pc."""

    def test_scan_asks_before_inspect(self):
        tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
        scan = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'scan')
        ask_line = inspect_line = None
        for node in ast.walk(scan):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == 'askyesno':
                    self.assertTrue(any(isinstance(a, ast.Name) and a.id == 'SCAN_CONFIRMATION' for a in node.args))
                    ask_line = node.lineno
                if isinstance(func, ast.Name) and func.id == 'inspect_pc':
                    inspect_line = node.lineno
        self.assertIsNotNone(ask_line)
        self.assertIsNotNone(inspect_line)
        self.assertLess(ask_line, inspect_line)


class ScanGuiTests(unittest.TestCase):
    """Com Tk (pula na nuvem sem Tk): "Não" não lê nada; "Sim" lê uma vez."""

    def _panel(self):
        try:
            import tkinter as tk
        except ImportError:
            self.skipTest('Sem Tk neste ambiente')
        import tempfile
        import optimization_ui
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('Sem servidor gráfico')
        track_tk_root(self, root)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': folder.name}):
            panel = optimization_ui.OptimizationPanel(root, folder.name)
        return optimization_ui, panel

    def test_no_does_not_inspect(self):
        ui, panel = self._panel()
        with mock.patch.object(ui.messagebox, 'askyesno', return_value=False) as ask, \
                mock.patch.object(ui, 'inspect_pc') as inspect, \
                mock.patch.object(ui, 'threading', SimpleNamespace(Thread=mock.Mock())) as fake_threading:
            panel.scan()
        thread = fake_threading.Thread
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[1], hp.SCAN_CONFIRMATION)
        inspect.assert_not_called()
        thread.assert_not_called()
        self.assertFalse(panel.running)

    def test_yes_inspects_once(self):
        ui, panel = self._panel()

        class InlineThread:
            def __init__(self, target=None, daemon=None, **kwargs):
                self.target = target

            def start(self):
                self.target()

        report = {'hardware': {}, 'power': {}, 'checks': [], 'errors': [], 'profile': hp.build_profile({})}
        with mock.patch.object(ui.messagebox, 'askyesno', return_value=True), \
                mock.patch.object(ui, 'inspect_pc', return_value=report) as inspect, \
                mock.patch.object(ui, 'threading', SimpleNamespace(Thread=InlineThread)), \
                mock.patch.object(panel, 'load_plans') as load_plans:
            panel.scan()
            panel.update()
        inspect.assert_called_once_with()
        self.assertIs(panel.running, False)
        self.assertIn('PERFIL DO SEU PC', panel.report_text.get('1.0', 'end'))
        load_plans.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
