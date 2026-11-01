"""FIX-P3-06-01: o JSON exportado não leva o modelo da placa nem o modelo do PC.

Só dicionários sintéticos e TemporaryDirectory; o PowerShell é simulado.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import optimization_engine as oe
from bios_guidance import build_bios_guidance
from hardware_profile import build_profile


def _report():
    hardware = {
        'cpu': {'Name': 'AMD Ryzen 5 5600', 'NumberOfCores': 6, 'NumberOfLogicalProcessors': 12,
                'SystemName': 'PC-DO-FULANO', 'SerialNumber': 'SN-CPU-1'},
        'gpu': [{'Name': 'NVIDIA GeForce RTX 3060', 'DriverVersion': '31.0.15.1', 'PNPDeviceID': 'PCI-XYZ'}],
        'ram': [{'Capacity': 8589934592, 'Speed': 3200, 'ConfiguredClockSpeed': 2133,
                 'Manufacturer': 'Kingston', 'DeviceLocator': 'DIMM A1', 'BankLabel': 'Channel A',
                 'SerialNumber': 'SN-RAM-1'},
                {'Capacity': 8589934592, 'Speed': 3200, 'ConfiguredClockSpeed': 2133,
                 'Manufacturer': 'Kingston', 'DeviceLocator': 'DIMM B1', 'BankLabel': 'Channel B',
                 'SerialNumber': 'SN-RAM-2'}],
        'board': {'Manufacturer': 'ASUSTeK COMPUTER INC.', 'Product': 'ROG STRIX B550-F GAMING',
                  'SerialNumber': 'MB-SERIAL-987654'},
        'bios': {'Manufacturer': 'American Megatrends Inc.', 'SMBIOSBIOSVersion': '2803',
                 'ReleaseDate': '/Date(1577836800000)/', 'SerialNumber': 'BIOS-SERIAL-123456'},
        'os': {'Caption': 'Microsoft Windows 11 Pro', 'Version': '10.0.22631', 'BuildNumber': '22631',
               'RegisteredUser': 'fulano'},
        'pc': {'Manufacturer': 'System manufacturer', 'Model': 'PC-DO-FULANO', 'PCSystemType': 1,
               'Name': 'DESKTOP-FULANO', 'UserName': 'FULANO\\fulano'},
        'chassis': {'ChassisTypes': [3]},
        'battery': None,
        'disks': [{'MediaType': 4, 'BusType': 17, 'Size': 1000204886016, 'FriendlyName': 'Disco do Fulano',
                   'SerialNumber': 'SN-DISK-1'}],
    }
    return {'timestamp': 'x', 'status': 'leitura', 'windows': True, 'hardware': hardware,
            'power': {}, 'checks': [], 'errors': []}


def _export(report):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / 'inventario.json'
        oe.export_snapshot(report, target)
        text = target.read_text(encoding='utf-8')
    return text, json.loads(text)


class ExportWithoutModelTests(unittest.TestCase):
    def test_json_has_no_model_serial_or_names(self):
        text, data = _export(_report())
        for secret in ('ROG STRIX B550-F', 'PC-DO-FULANO', 'DESKTOP-FULANO', 'fulano', 'SerialNumber',
                       'SERIAL', 'SN-', 'Product', 'Model', 'UserName', 'SystemName', 'FriendlyName',
                       'Disco do Fulano', 'PNPDeviceID', 'RegisteredUser'):
            self.assertNotIn(secret, text)
        self.assertNotIn('Name', data['hardware']['pc'])
        self.assertEqual(data['hardware']['board'], {'Manufacturer': 'ASUSTeK COMPUTER INC.'})
        self.assertEqual(data['hardware']['pc'], {'Manufacturer': 'System manufacturer', 'PCSystemType': 1})
        self.assertEqual(data['hardware']['cpu']['Name'], 'AMD Ryzen 5 5600')
        self.assertEqual(data['hardware']['gpu'][0]['Name'], 'NVIDIA GeForce RTX 3060')

    def test_original_report_is_not_changed(self):
        report = _report()
        before = copy.deepcopy(report)
        _export(report)
        self.assertEqual(report, before)
        self.assertEqual(report['hardware']['board']['Product'], 'ROG STRIX B550-F GAMING')

    def test_top_level_keys_kept(self):
        _, data = _export({'a': 1})
        self.assertEqual(data, {'a': 1})
        report = _report()
        report['profile'] = {'tier': 'gamer'}
        _, data = _export(report)
        self.assertEqual(data['profile'], {'tier': 'gamer'})
        self.assertEqual(data['status'], 'leitura')

    def test_bad_values_do_not_fail(self):
        report = _report()
        report['hardware'].update({'cpu': None, 'gpu': 'texto', 'ram': 42,
                                   'board': [{'Manufacturer': 'X', 'Product': 'P'}, 'lixo', 7],
                                   'desconhecida': {'Name': 'PC-DO-FULANO'}})
        text, data = _export(report)
        self.assertNotIn('desconhecida', data['hardware'])
        self.assertNotIn('cpu', data['hardware'])
        self.assertNotIn('gpu', data['hardware'])
        self.assertNotIn('ram', data['hardware'])
        self.assertEqual(data['hardware']['board'], [{'Manufacturer': 'X'}])
        self.assertNotIn('PC-DO-FULANO', text)

    def test_hardware_not_dict_is_dropped(self):
        for value in (None, 'texto', 42, [1, 2]):
            with self.subTest(value=value):
                _, data = _export({'hardware': value, 'a': 1})
                self.assertEqual(data, {'a': 1})

    def test_round_trip_profile_and_guidance(self):
        report = _report()
        _, data = _export(report)
        self.assertEqual(build_profile(data['hardware']), build_profile(report['hardware']))
        profile = build_profile(report['hardware'])
        self.assertEqual(build_bios_guidance(data['hardware'], profile),
                         build_bios_guidance(report['hardware'], profile))


    def test_round_trip_variants(self):
        variants = {
            'sem bateria (None)': {'battery': None},
            'sem bateria (lista vazia)': {'battery': []},
            'com bateria': {'battery': {'BatteryStatus': 2, 'DeviceID': 'BAT-FULANO'}},
            'bateria em lista': {'battery': [{'BatteryStatus': 1}]},
            'bateria mista': {'battery': [{'BatteryStatus': 1}, 'lixo']},
            'bateria texto': {'battery': 'texto'},
            'notebook': {'pc': {'Manufacturer': 'Fab', 'Model': 'Mod', 'PCSystemType': 2}},
            'listas mistas': {'cpu': [{'Name': 'CPU', 'NumberOfCores': 4}, 'x', 3],
                              'disks': [], 'gpu': None, 'ram': 'texto', 'chassis': 7},
        }
        for name, change in variants.items():
            with self.subTest(name=name):
                report = _report()
                report['hardware'].update(change)
                _, data = _export(report)
                profile = build_profile(report['hardware'])
                self.assertEqual(build_profile(data['hardware']), profile)
                self.assertEqual(build_bios_guidance(data['hardware'], profile),
                                 build_bios_guidance(report['hardware'], profile))
        report = _report()
        del report['hardware']['battery']
        _, data = _export(report)
        self.assertNotIn('battery', data['hardware'])
        self.assertEqual(build_profile(data['hardware']), build_profile(report['hardware']))


class InspectQueriesTests(unittest.TestCase):
    def test_no_query_reads_model(self):
        calls = []

        def fake_ps(code, timeout=22):
            calls.append(code)
            return None

        with patch.object(oe, '_is_windows', return_value=True), \
                patch.object(oe, '_ps', side_effect=fake_ps), \
                patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')):
            oe.inspect_pc()
        self.assertEqual(len(calls), 10)
        for code in calls:
            self.assertNotIn('Model', code)
        self.assertTrue(any('Win32_ComputerSystem' in c and 'PCSystemType' in c for c in calls))


if __name__ == '__main__':
    unittest.main()
