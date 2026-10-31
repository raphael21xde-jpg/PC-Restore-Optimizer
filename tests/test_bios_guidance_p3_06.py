"""P3-06 fatia 1: BIOS só orientação (XMP/EXPO, versão e passo a passo).

Só dados sintéticos: nenhum comando real, nenhum PowerShell, registro ou WMI.
"""
import ast
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import bios_guidance as bg  # noqa: E402
import optimization_engine as oe  # noqa: E402
from tk_helpers import track_tk_root  # noqa: E402

try:
    import tkinter as tk
    import optimization_ui as ou
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ou = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _ram(*pairs):
    return [{'Speed': s, 'ConfiguredClockSpeed': c, 'Capacity': 8 * 1024 ** 3} for s, c in pairs]


class XmpStateTests(unittest.TestCase):
    def test_one_below_and_other_above_is_not_confirmed(self):
        state, reason = bg.xmp_state(_ram((3200, 3600), (3200, 2133)))
        self.assertEqual(state, bg.XMP_UNKNOWN)
        self.assertEqual(reason, bg.REASON_MIXED)
        text = '\n'.join(bg.bios_guidance_lines({'xmp': state, 'xmp_reason': reason}))
        self.assertIn('Perfil de memória (XMP/EXPO): não confirmado', text)
        self.assertIn('Os módulos de memória informam velocidades diferentes; não dá para saber.', text)

    def test_below_and_none_above_means_off(self):
        state, reason = bg.xmp_state(_ram((3200, 3200), (3200, 2133)))
        self.assertEqual(state, bg.XMP_OFF)
        self.assertIn('2133', reason)
        self.assertIn('3200', reason)
        text = '\n'.join(bg.bios_guidance_lines({'xmp': state, 'xmp_reason': reason}))
        self.assertIn('provavelmente desligado (ou limitado pelo processador/placa)', text)
        self.assertIn('configurada a 2133 MT/s e o módulo informa 3200 MT/s', text)

    def test_exact_half_is_not_confirmed_units(self):
        for ram in (_ram((3200, 1600)), _ram((3200, 1600), (3200, 3200)), _ram((2133, 3200), (3600, 1800))):
            with self.subTest(ram=ram):
                state, reason = bg.xmp_state(ram)
                self.assertEqual((state, reason), (bg.XMP_UNKNOWN, bg.REASON_UNITS))
        text = '\n'.join(bg.bios_guidance_lines({'xmp': bg.XMP_UNKNOWN, 'xmp_reason': bg.REASON_UNITS}))
        self.assertIn('Perfil de memória (XMP/EXPO): não confirmado', text)
        self.assertIn('diferença de unidade (MHz e MT/s)', text)

    def test_single_dict_below_means_off(self):
        self.assertEqual(bg.xmp_state({'Speed': 3600, 'ConfiguredClockSpeed': 2400})[0], bg.XMP_OFF)

    def test_all_above_means_on(self):
        state, reason = bg.xmp_state(_ram((2133, 3200), (2133, 3200)))
        self.assertEqual(state, bg.XMP_ON)
        text = '\n'.join(bg.bios_guidance_lines({'xmp': state, 'xmp_reason': reason}))
        self.assertIn('Perfil de memória (XMP/EXPO): provavelmente ligado', text)
        self.assertIn(bg._DEFAULT_REASONS[bg.XMP_ON], text)

    def test_doubtful_values_are_not_confirmed(self):
        cases = {
            'iguais': _ram((3200, 3200)),
            'ausente': [{'Speed': 3200}],
            'zero': _ram((3200, 0)),
            'texto': _ram(('3200', '3600')),
            'bool': _ram((True, 3600)),
            'nan': _ram((float('nan'), 3600)),
            'infinito': _ram((2133, float('inf'))),
            'lista vazia': [],
            'nada': None,
            'texto solto': 'DDR4',
            'misto': _ram((2133, 3200)) + [{'Speed': 3200}],
            'lixo na lista': [1, 'a', None],
        }
        for name, ram in cases.items():
            with self.subTest(name):
                self.assertEqual(bg.xmp_state(ram)[0], bg.XMP_UNKNOWN)


class BoardFamilyTests(unittest.TestCase):
    def test_known_brands(self):
        cases = {'ASUSTeK COMPUTER INC.': 'asus', 'Micro-Star International Co., Ltd.': 'msi',
                 'Gigabyte Technology Co., Ltd.': 'gigabyte', 'ASRock': 'asrock'}
        for maker, family in cases.items():
            with self.subTest(maker):
                self.assertEqual(bg.board_family({'Manufacturer': maker}, {}, 'desktop'), family)
                self.assertEqual(bg.board_family([{'Manufacturer': maker}], None, 'desconhecido'), family)

    def test_notebook_and_oem(self):
        self.assertEqual(bg.board_family({'Manufacturer': 'ASUSTeK COMPUTER INC.'}, {}, 'notebook'), 'oem')
        for maker in ('Dell Inc.', 'HP', 'Hewlett-Packard', 'LENOVO', 'Acer', 'Positivo Tecnologia SA',
                      'SAMSUNG ELECTRONICS CO., LTD.'):
            with self.subTest(maker):
                self.assertEqual(bg.board_family({'Manufacturer': maker}, {}, 'desktop'), 'oem')
        self.assertEqual(bg.board_family({'Manufacturer': 'Intel'}, {'Manufacturer': 'Dell Inc.'}, None), 'oem')

    def test_empty_or_strange_is_unknown(self):
        for board in (None, {}, {'Manufacturer': ''}, {'Manufacturer': 42}, 'ASUS', [1, 2],
                      {'Manufacturer': 'To Be Filled By O.E.M.'}):
            with self.subTest(board=board):
                self.assertEqual(bg.board_family(board, {'Manufacturer': 'American Megatrends Inc.'},
                                                 'desktop'), 'desconhecido')


class BiosYearTests(unittest.TestCase):
    def test_two_formats(self):
        self.assertEqual(bg.bios_release_year('/Date(1577836800000)/'), 2020)
        self.assertEqual(bg.bios_release_year('20190715000000.000000+000'), 2019)
        self.assertEqual(bg.bios_release_year('20210102'), 2021)

    def test_garbage_old_or_future_is_none(self):
        future = datetime.now(timezone.utc).year + 1
        for value in (None, '', 'ontem', 2020, True, '2020-01-01T00:00:00', '19850101',
                      f'{future}0101', '29991231', '20201345', '/Date(-999999999999999)/',
                      '/Date(abc)/', '/Date(1)/', ['20200101'], {'x': 1}):
            with self.subTest(value=value):
                self.assertIsNone(bg.bios_release_year(value))


def _hardware():
    return {
        'ram': _ram((3200, 2133)),
        'board': {'Manufacturer': 'ASUSTeK COMPUTER INC.', 'Product': 'ROG STRIX B550-F GAMING',
                  'SerialNumber': 'MB-SERIAL-987654'},
        'bios': {'Manufacturer': 'American Megatrends Inc.', 'SMBIOSBIOSVersion': '2803',
                 'ReleaseDate': '/Date(1577836800000)/', 'SerialNumber': 'BIOS-SERIAL-123456'},
        'pc': {'Manufacturer': 'System manufacturer', 'Model': 'PC-DO-FULANO', 'PCSystemType': 1},
    }


class GuidanceTests(unittest.TestCase):
    def test_build_guidance_fields(self):
        guidance = bg.build_bios_guidance(_hardware(), {'form_factor': 'desktop'})
        self.assertEqual(guidance['xmp'], bg.XMP_OFF)
        self.assertEqual(guidance['family'], 'asus')
        self.assertEqual(guidance['bios_version'], '2803')
        self.assertEqual(guidance['bios_year'], 2020)
        self.assertEqual(guidance['rebar'], 'nao_verificado')
        self.assertTrue(guidance['steps'])
        self.assertIn('limpe a CMOS', guidance['steps'][-1])
        self.assertTrue(any('AI Tweaker' in s and 'D.O.C.P' in s for s in guidance['steps']))

    def test_every_generated_text_says_app_never_changes_bios(self):
        inputs = [
            bg.build_bios_guidance(_hardware(), {'form_factor': 'desktop'}),
            bg.build_bios_guidance(_hardware(), {'form_factor': 'notebook'}),
            bg.build_bios_guidance({}, {}),
            bg.build_bios_guidance(None, None),
            {}, None, 'lixo', 42, [1, 2],
            {'xmp': 'ligadissimo', 'family': 'hackers', 'bios_version': 'C:\\Users\\fulano',
             'bios_year': 1800, 'steps': 'nao e lista', 'xmp_reason': {'a': 1}},
        ]
        for guidance in inputs:
            with self.subTest(guidance=str(guidance)[:40]):
                text = '\n'.join(bg.bios_guidance_lines(guidance))
                self.assertIn('O app nunca altera a BIOS', text)
                self.assertIn('BIOS — SÓ ORIENTAÇÃO', text)
                self.assertIn('limpe a CMOS', text)

    def test_strange_entries_become_not_confirmed(self):
        text = '\n'.join(bg.bios_guidance_lines({'xmp': 'ligado', 'family': 123}))
        self.assertIn('Perfil de memória (XMP/EXPO): não confirmado', text)
        self.assertIn('Fabricante da placa: não identificado', text)
        self.assertIn('versão não disponível', text)

    def test_oem_text_mentions_manual(self):
        text = '\n'.join(bg.bios_guidance_lines(bg.build_bios_guidance(_hardware(), {'form_factor': 'notebook'})))
        self.assertIn('não têm XMP/EXPO', text)
        self.assertIn('manual do fabricante', text)

    def test_version_year_and_maker_are_shown(self):
        text = '\n'.join(bg.bios_guidance_lines(bg.build_bios_guidance(_hardware(), {'form_factor': 'desktop'})))
        self.assertIn('  BIOS: versão 2803 | ano 2020', text)
        self.assertIn('  Fabricante da placa: ASUS', text)
        self.assertIn('AI Tweaker', text)
        self.assertIn('D.O.C.P', text)

    def test_steps_per_family_in_shown_text(self):
        cases = {
            'Micro-Star International Co., Ltd.': ('MSI', ['"OC"', '"A-XMP"', '"XMP" ou "EXPO"']),
            'Gigabyte Technology Co., Ltd.': ('Gigabyte', ['"Tweaker"', 'Extreme Memory Profile (XMP)', '"EXPO"']),
            'ASRock': ('ASRock', ['"OC Tweaker"', '"Load XMP Setting"', '"EXPO"']),
            'Fabricante Qualquer': ('não identificado', ['"OC", "Tweaker", "Avançado"',
                                                         'DEL ou F2 (ou a tecla indicada na tela de abertura)']),
        }
        for maker, (label, words) in cases.items():
            with self.subTest(maker):
                hardware = _hardware()
                hardware['board'] = {'Manufacturer': maker}
                text = '\n'.join(bg.bios_guidance_lines(bg.build_bios_guidance(hardware, {'form_factor': 'desktop'})))
                self.assertIn(f'  Fabricante da placa: {label}', text)
                for word in words:
                    self.assertIn(word, text)
                self.assertIn('limpe a CMOS', text)

    def test_foreign_steps_are_ignored_and_safety_stays(self):
        guidance = bg.build_bios_guidance(_hardware(), {'form_factor': 'desktop'})
        guidance['steps'] = ['C:\\Users\\fulano\\apague.bat', 'Desligue o Defender']
        text = '\n'.join(bg.bios_guidance_lines(guidance))
        self.assertNotIn('fulano', text)
        self.assertNotIn('Defender', text)
        self.assertIn('limpe a CMOS', text)
        self.assertIn('Não mude o CSM', text)
        self.assertIn('AI Tweaker', text)

    def test_no_update_recommendation_or_links(self):
        text = '\n'.join(bg.bios_guidance_lines(bg.build_bios_guidance(_hardware(), {})))
        self.assertIn('O app não pede para atualizar a BIOS. Se você decidir atualizar, use só o site oficial', text)
        self.assertNotIn('http', text.lower())
        self.assertNotIn('www.', text.lower())
        self.assertNotIn('download', text.lower())


class PrivacyTests(unittest.TestCase):
    def test_no_model_serial_or_paths(self):
        hardware = _hardware()
        guidance = bg.build_bios_guidance(hardware, {'form_factor': 'desktop'})
        text = repr(guidance) + '\n'.join(bg.bios_guidance_lines(guidance))
        for secret in ('ROG STRIX', 'B550', 'MB-SERIAL-987654', 'BIOS-SERIAL-123456', 'PC-DO-FULANO'):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, text)

    def test_version_that_looks_like_path_or_is_long_is_dropped(self):
        for version in ('C:\\Users\\fulano\\bios.rom', '/home/fulano/bios', '%USERPROFILE%', 'A' * 41,
                        '~fulano', 'versão<script>', 12):
            with self.subTest(version=version):
                hardware = _hardware()
                hardware['bios']['SMBIOSBIOSVersion'] = version
                guidance = bg.build_bios_guidance(hardware, {})
                self.assertIsNone(guidance['bios_version'])
                text = '\n'.join(bg.bios_guidance_lines(guidance))
                self.assertNotIn('fulano', text)
                self.assertIn('versão não disponível', text)

    def test_foreign_reason_text_is_not_shown(self):
        text = '\n'.join(bg.bios_guidance_lines({'xmp': bg.XMP_OFF, 'xmp_reason': 'C:\\Users\\fulano'}))
        self.assertNotIn('fulano', text)


class ReadOnlyTests(unittest.TestCase):
    def test_module_imports_no_system_access(self):
        tree = ast.parse((ROOT / 'bios_guidance.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        for forbidden in ('subprocess', 'os', 'winreg', 'tkinter', 'ctypes', 'shutil',
                          'optimization_engine', 'hardware_profile'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, imported)


class EngineTests(unittest.TestCase):
    def test_inspect_outside_windows_has_unconfirmed_guidance(self):
        with mock.patch.object(oe, '_is_windows', return_value=False), \
                mock.patch.object(oe, '_ps', _forbidden), mock.patch.object(oe, '_run', _forbidden), \
                mock.patch.object(subprocess, 'run', _forbidden):
            report = oe.inspect_pc()
        guidance = report['bios_guidance']
        self.assertEqual(guidance['xmp'], bg.XMP_UNKNOWN)
        self.assertEqual(guidance['family'], 'desconhecido')
        self.assertIsNone(guidance['bios_version'])
        self.assertIsNone(guidance['bios_year'])
        self.assertEqual(guidance['rebar'], 'nao_verificado')

    def test_inspect_on_simulated_windows_uses_existing_queries(self):
        hardware = _hardware()
        answers = {'Win32_PhysicalMemory': hardware['ram'], 'Win32_BaseBoard': hardware['board'],
                   'Win32_BIOS': hardware['bios']}
        calls = []

        def fake_ps(code, timeout=22):
            calls.append(code)
            for key, value in answers.items():
                if key in code:
                    return value
            return None
        with mock.patch.object(oe, '_is_windows', return_value=True), \
                mock.patch.object(oe, '_ps', fake_ps), mock.patch.object(oe, '_run', _forbidden), \
                mock.patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')), \
                mock.patch.object(subprocess, 'run', _forbidden):
            report = oe.inspect_pc()
        self.assertEqual(len(calls), 10)  # nenhuma consulta nova
        guidance = report['bios_guidance']
        self.assertEqual((guidance['xmp'], guidance['family'], guidance['bios_year']),
                         (bg.XMP_OFF, 'asus', 2020))
        self.assertTrue(any(c.get('state') == 'verificar' and c.get('type') == 'ram' for c in report['checks']))


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class ScreenTests(unittest.TestCase):
    def setUp(self):
        for name in ('_run', '_ps'):
            patcher = mock.patch.object(oe, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)

    def test_scan_finished_shows_bios_section(self):
        panel = ou.OptimizationPanel(self.root, app_dir=self.tmp, state_dir=self.tmp,
                                     ask=lambda *a: False, show=lambda *a: None)
        panel.pack()
        hardware = _hardware()
        report = {'hardware': hardware, 'power': {}, 'checks': [], 'errors': [], 'unmeasured': [],
                  'profile': {'form_factor': 'desktop'},
                  'bios_guidance': bg.build_bios_guidance(hardware, {'form_factor': 'desktop'})}
        with mock.patch.object(panel, 'load_plans', lambda: None):
            panel._scan_finished(report)
        text = panel.report_text.get('1.0', 'end')
        self.assertIn('BIOS — SÓ ORIENTAÇÃO', text)
        self.assertIn('O app nunca altera a BIOS', text)
        self.assertIn('provavelmente desligado', text)
        self.assertLess(text.index('PERFIL DO SEU PC'), text.index('BIOS — SÓ ORIENTAÇÃO'))
        self.assertLess(text.index('BIOS — SÓ ORIENTAÇÃO'), text.index('OBSERVAÇÕES:'))


class UiWiringTests(unittest.TestCase):
    def test_scan_finished_calls_bios_lines_after_profile(self):
        tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
        scan = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_scan_finished')
        lines = {}
        for node in ast.walk(scan):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                lines.setdefault(node.func.id, node.lineno)
        self.assertIn('bios_guidance_lines', lines)
        self.assertLess(lines['profile_lines'], lines['bios_guidance_lines'])


if __name__ == '__main__':
    unittest.main()
