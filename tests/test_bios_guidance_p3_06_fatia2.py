"""P3-06 fatia 2: Resizable BAR só lendo e botão "Ver passo a passo".

Só dados sintéticos: nenhum comando real, nenhum PowerShell, registro ou WMI.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
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

MIB = 1024 ** 2


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _bar(*sizes):
    return [{'Sizes': list(sizes)}]


def _hardware(gpu_bar=None):
    hardware = {
        'ram': [{'Speed': 3200, 'ConfiguredClockSpeed': 2133}],
        'board': {'Manufacturer': 'ASUSTeK COMPUTER INC.'},
        'bios': {'Manufacturer': 'American Megatrends Inc.', 'SMBIOSBIOSVersion': '2803',
                 'ReleaseDate': '/Date(1577836800000)/'},
    }
    if gpu_bar is not None:
        hardware['gpu_bar'] = gpu_bar
    return hardware


def _text(guidance):
    return '\n'.join(bg.bios_guidance_lines(guidance))


class RebarStateTests(unittest.TestCase):
    def test_window_above_256_mib_is_not_confirmed(self):
        # FIX-M3-T1: janela grande sozinha não confirma o Resizable BAR.
        state, reason = bg.rebar_state(_bar(16 * MIB, 8192 * MIB, 32 * 1024))
        self.assertEqual(state, bg.REBAR_UNKNOWN)
        self.assertEqual(reason, bg.REBAR_REASON_BIG)

    def test_several_gpus_only_one_large_is_mixed(self):
        # FIX-P3-06-13 (R-38): antes bastava uma placa; agora todas precisam concordar.
        value = [{'Sizes': [256 * MIB, 16 * MIB]}, {'Sizes': [16 * 1024 ** 3]}]
        self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_MIXED))
        self.assertEqual(bg.rebar_state({'Sizes': [512 * MIB]}), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_BIG))

    def test_all_up_to_256_mib_is_not_confirmed(self):
        state, reason = bg.rebar_state(_bar(256 * MIB, 16 * MIB, 128 * 1024))
        self.assertEqual(state, bg.REBAR_UNKNOWN)
        self.assertEqual(reason, bg.REBAR_REASON_SMALL)

    def test_strange_input_is_not_confirmed_without_exception(self):
        strange = [None, [], {}, 'texto', 42, True, float('nan'), [None, 'x', 3],
                   _bar(), _bar(-1), _bar(-(512 * MIB)), _bar('600000000'), _bar(True),
                   _bar(float('nan')), _bar(float('inf')), _bar(1.5e9 + 0.5), _bar(0),
                   _bar(2 ** 60), [{'Sizes': 'texto'}], [{'Outro': [512 * MIB]}],
                   [{'Sizes': [[512 * MIB]]}], [{'Sizes': {'a': 512 * MIB}}],
                   json.loads('{"Sizes": null}'), json.loads('[[1, 2], {"Sizes": [false]}]')]
        for value in strange:
            with self.subTest(value=value):
                state, reason = bg.rebar_state(value)
                self.assertEqual(state, bg.REBAR_UNKNOWN)
                self.assertIn(reason, (bg.REBAR_REASON_DEFAULT, bg.REBAR_REASON_SMALL))
                self.assertNotIn('desligado', reason.lower())

    def test_integrated_256_mib_and_dedicated_8_gib_is_mixed(self):
        value = [{'Sizes': [256 * MIB, 16 * MIB]}, {'Sizes': [8 * 1024 ** 3, 32 * MIB]}]
        self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_MIXED))

    def test_two_dedicated_above_256_mib_is_big(self):
        value = [{'Sizes': [8 * 1024 ** 3]}, {'Sizes': [16 * MIB, 512 * MIB]}]
        self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_BIG))

    def test_dedicated_and_gpu_without_sizes_is_mixed(self):
        for other in ({}, {'Sizes': None}, {'Sizes': []}, {'Sizes': 'x'}, {'Sizes': {'value': []}}):
            with self.subTest(other=other):
                value = [{'Sizes': [8 * 1024 ** 3]}, other]
                self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_MIXED))

    def test_dedicated_and_non_dict_item_is_mixed(self):
        for other in (None, 'texto', 42, [8 * 1024 ** 3]):
            with self.subTest(other=other):
                value = [{'Sizes': [8 * 1024 ** 3]}, other]
                self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_MIXED))

    def test_all_gpus_small_is_small(self):
        value = [{'Sizes': [256 * MIB]}, {'Sizes': [16 * MIB, 128 * MIB]}]
        self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_SMALL))

    def test_small_and_gpu_without_data_is_mixed(self):
        # FIX-P3-06-14: placa pequena junto de placa sem dado não vira SMALL (a sem dado pode ser a grande).
        for value in ([{'Sizes': [256 * MIB]}, {}],
                      [{'Sizes': [16 * MIB]}, None],
                      [{'Sizes': [128 * MIB]}, {'Sizes': {'value': []}}]):
            with self.subTest(value=value):
                state, reason = bg.rebar_state(value)
                self.assertEqual((state, reason), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_MIXED))
                self.assertNotIn('desligado', reason.lower())

    def test_all_gpus_without_data_is_default(self):
        self.assertEqual(bg.rebar_state([{}, None]), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_DEFAULT))

    def test_single_large_gpu_is_big(self):
        self.assertEqual(bg.rebar_state(_bar(8 * 1024 ** 3)), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_BIG))
        self.assertEqual(bg.rebar_state({'Sizes': [8 * 1024 ** 3]}), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_BIG))

    def test_lines_accept_mixed_reason(self):
        text = _text({'rebar': bg.REBAR_UNKNOWN, 'rebar_reason': bg.REBAR_REASON_MIXED})
        self.assertIn('Resizable BAR: não confirmado', text)
        self.assertIn(bg.REBAR_REASON_MIXED, text)
        self.assertIn(bg.REBAR_REASON_MIXED, bg._REBAR_REASONS[bg.REBAR_UNKNOWN])
        # FIX-M3-T1: estado antigo "provavelmente_ligado" vira "não confirmado".
        text = _text({'rebar': 'provavelmente_ligado', 'rebar_reason': bg.REBAR_REASON_MIXED})
        self.assertIn('Resizable BAR: não confirmado', text)
        self.assertIn(bg.REBAR_REASON_MIXED, text)

    def test_mixed_reason_wording(self):
        self.assertEqual(bg.REBAR_REASON_MIXED,
                         'As placas de vídeo do PC não informam a mesma coisa (por exemplo, vídeo integrado '
                         'e placa dedicada, ou uma delas sem informação); não dá para confirmar o Resizable BAR.')
        self.assertEqual(bg.REBAR_REASON_BIG,
                         'O Windows informa uma janela de memória maior que 256 MiB, mas isso sozinho não '
                         'confirma o Resizable BAR (há placas que mostram isso com ele desligado).')

    def test_never_says_off(self):
        for value in (None, _bar(16 * MIB), _bar(512 * MIB), 'x'):
            with self.subTest(value=value):
                guidance = bg.build_bios_guidance(_hardware(value), {'form_factor': 'desktop'})
                line = next(l for l in bg.bios_guidance_lines(guidance) if 'Resizable BAR:' in l)
                self.assertNotIn('desligad', line.lower())
                # REBAR_REASON_BIG cita "com ele desligado" só como exemplo; nunca diz que está desligado.
                reason = guidance['rebar_reason'].replace('com ele desligado', '')
                self.assertNotIn('desligad', reason.lower())
        for label in bg.REBAR_LABELS.values():
            self.assertNotIn('desligad', label)


class PowerShellWrappedTests(unittest.TestCase):
    """FIX-P3-06-13: ConvertTo-Json do PowerShell 5.1 pode embrulhar listas em {"value": [...]}."""

    def test_wrapped_gpu_list_is_big(self):
        value = json.loads('{"value": [{"Sizes": [8589934592]}], "Count": 1}')
        self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_BIG))

    def test_wrapped_sizes_is_big(self):
        value = json.loads('[{"Sizes": {"value": [8589934592], "Count": 1}}]')
        self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_BIG))

    def test_wrapped_strange_is_default_without_exception(self):
        for value in ({'value': []}, {'value': 'x'}, {'value': None}, {'value': {'Sizes': [8 * 1024 ** 3]}},
                      [{'Sizes': {'value': 'x'}}]):
            with self.subTest(value=value):
                self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_DEFAULT))

    def test_ps_list(self):
        self.assertEqual(bg._ps_list([1, 2]), [1, 2])
        self.assertEqual(bg._ps_list({'value': [1], 'Count': 1}), [1])
        for value in (None, 'x', 3, {}, {'value': 'x'}, {'Sizes': [1]}):
            with self.subTest(value=value):
                self.assertEqual(bg._ps_list(value), [])

    def test_inspect_pc_with_wrapped_output_is_not_confirmed(self):
        def fake_ps(code, timeout=22):
            if 'Win32_DeviceMemoryAddress' in code:
                return json.loads('{"value": [{"Sizes": {"value": [8589934592], "Count": 1}}], "Count": 1}')
            return None
        with mock.patch.object(oe, '_is_windows', return_value=True), \
                mock.patch.object(oe, '_ps', side_effect=fake_ps), \
                mock.patch.object(oe, '_run', _forbidden), \
                mock.patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')), \
                mock.patch.object(subprocess, 'run', _forbidden):
            report = oe.inspect_pc()
        self.assertEqual(report['bios_guidance']['rebar'], bg.REBAR_UNKNOWN)
        self.assertEqual(report['bios_guidance']['rebar_reason'], bg.REBAR_REASON_BIG)


class GuidanceRebarTests(unittest.TestCase):
    def test_build_guidance_has_rebar_and_reason(self):
        guidance = bg.build_bios_guidance(_hardware(_bar(8 * 1024 ** 3)), {'form_factor': 'desktop'})
        self.assertEqual(guidance['rebar'], bg.REBAR_UNKNOWN)
        self.assertEqual(guidance['rebar_reason'], bg.REBAR_REASON_BIG)
        guidance = bg.build_bios_guidance({}, {})
        self.assertEqual(guidance['rebar'], bg.REBAR_UNKNOWN)
        self.assertEqual(guidance['rebar_reason'], bg.REBAR_REASON_DEFAULT)

    def test_lines_depend_on_state(self):
        on = _text(bg.build_bios_guidance(_hardware(_bar(8 * 1024 ** 3)), {}))
        self.assertIn('  Resizable BAR: não confirmado', on)
        self.assertIn(bg.REBAR_REASON_BIG, on)
        unknown = _text(bg.build_bios_guidance(_hardware(_bar(256 * MIB)), {}))
        self.assertIn('  Resizable BAR: não confirmado', unknown)
        self.assertIn(bg.REBAR_REASON_SMALL, unknown)
        for text in (on, unknown):
            self.assertNotIn('não verificado nesta versão', text)
            self.assertIn('Não mude o CSM', text)
            self.assertIn('nem o modo de inicialização', text)

    def test_lines_only_accept_module_reasons(self):
        text = _text({'rebar': bg.REBAR_UNKNOWN, 'rebar_reason': 'Clique em http://exemplo para baixar'})
        self.assertNotIn('http', text)
        self.assertIn(bg.REBAR_REASON_DEFAULT, text)
        old_on = ('O Windows informa, para cada placa de vídeo, uma janela de memória maior que 256 MiB; '
                  'isso costuma indicar Resizable BAR ligado.')
        for state in ('desligado', 'provavelmente_ligado'):
            with self.subTest(state=state):
                text = _text({'rebar': state, 'rebar_reason': old_on})
                self.assertIn('Resizable BAR: não confirmado', text)
                self.assertNotIn(old_on, text)
                self.assertIn(bg.REBAR_REASON_DEFAULT, text)

    def test_no_automatic_above_4g(self):
        for value in (_bar(8 * 1024 ** 3), None):
            guidance = bg.build_bios_guidance(_hardware(value), {})
            for text in (_text(guidance), bg.bios_steps_text(guidance)):
                for forbidden in ('ligue o Above 4G', 'ative o Above 4G', 'Ligue o Above 4G',
                                  'Ative o Above 4G'):
                    self.assertNotIn(forbidden, text)


class StepsTextTests(unittest.TestCase):
    def test_steps_regenerated_by_family_ignoring_field(self):
        guidance = bg.build_bios_guidance(_hardware(), {'form_factor': 'desktop'})
        guidance['steps'] = ['Baixe a BIOS em http://exemplo e aperte F5']
        text = bg.bios_steps_text(guidance)
        self.assertNotIn('http', text)
        self.assertNotIn('Baixe', text)
        self.assertIn('AI Tweaker', text)
        self.assertIn(bg.NEVER_CHANGES, text)
        self.assertIn('limpe a CMOS', text)
        self.assertIn('Não mude o CSM', text)

    def test_steps_text_strange_input(self):
        for value in (None, 'x', [], {'family': 'inventada'}, {'family': ['asus']}):
            with self.subTest(value=value):
                text = bg.bios_steps_text(value)
                self.assertIn(bg.NEVER_CHANGES, text)
                self.assertIn('"OC", "Tweaker"', text)  # família não identificada
        self.assertIn('manual do fabricante', bg.bios_steps_text({'family': 'oem'}))

    def test_steps_text_has_no_link_or_download(self):
        for family in bg.FAMILY_LABELS:
            text = bg.bios_steps_text({'family': family})
            for forbidden in ('http', 'www.', 'download', 'Baixe'):
                self.assertNotIn(forbidden, text)


def _bar_query(calls):
    return next(c for c in calls if 'Win32_DeviceMemoryAddress' in c)


class InspectGpuBarTests(unittest.TestCase):
    def test_query_is_read_only_and_returns_only_sizes(self):
        calls = []

        def fake_ps(code, timeout=22):
            calls.append(code)
            if 'Win32_DeviceMemoryAddress' in code:
                return _bar(16 * MIB, 8 * 1024 ** 3)
            return None
        with mock.patch.object(oe, '_is_windows', return_value=True), \
                mock.patch.object(oe, '_ps', side_effect=fake_ps), \
                mock.patch.object(oe, '_run', _forbidden), \
                mock.patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')), \
                mock.patch.object(subprocess, 'run', _forbidden):
            report = oe.inspect_pc()
        self.assertEqual(len(calls), 11)
        code = _bar_query(calls)
        self.assertIn('Win32_VideoController', code)
        self.assertIn('Get-CimAssociatedInstance', code)
        self.assertIn('EndingAddress', code)
        self.assertIn('StartingAddress', code)
        for forbidden in ('PNPDeviceID', '.Name', 'Select-Object', 'Set-', 'Invoke-CimMethod', 'Remove-', 'New-',
                          'reg ', 'bcdedit', 'Start-Process', 'RunAs'):
            self.assertNotIn(forbidden, code)
        self.assertEqual(report['bios_guidance']['rebar'], bg.REBAR_UNKNOWN)
        self.assertEqual(report['bios_guidance']['rebar_reason'], bg.REBAR_REASON_BIG)

    def test_query_failure_message_without_powershell_text(self):
        def fake_ps(code, timeout=22):
            if 'Win32_DeviceMemoryAddress' in code:
                raise oe.OptimizationError('C:\\Users\\FULANO-SECRETO\\erro')
            return None
        with mock.patch.object(oe, '_is_windows', return_value=True), \
                mock.patch.object(oe, '_ps', side_effect=fake_ps), \
                mock.patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')):
            report = oe.inspect_pc()
        self.assertIn('Inventário Resizable BAR (placa de vídeo): não foi possível ler.', report['errors'])
        self.assertFalse([e for e in report['errors'] if 'gpu_bar' in e])
        self.assertNotIn('FULANO-SECRETO', json.dumps(report, ensure_ascii=False))
        self.assertEqual(report['bios_guidance']['rebar'], bg.REBAR_UNKNOWN)

    def test_outside_windows_no_command_and_not_confirmed(self):
        with mock.patch.object(oe, '_is_windows', return_value=False), \
                mock.patch.object(oe, '_ps', side_effect=_forbidden) as ps, \
                mock.patch.object(oe, '_run', side_effect=_forbidden), \
                mock.patch.object(subprocess, 'run', _forbidden):
            report = oe.inspect_pc()
        ps.assert_not_called()
        self.assertEqual(report['bios_guidance']['rebar'], bg.REBAR_UNKNOWN)
        self.assertNotIn('gpu_bar', report['hardware'])

    def test_ps_itself_never_runs_outside_windows(self):
        with mock.patch.object(oe, '_is_windows', return_value=False), \
                mock.patch.object(oe.shutil, 'which', return_value='powershell.exe'), \
                mock.patch.object(subprocess, 'run', side_effect=_forbidden) as run:
            with self.assertRaises(oe.OptimizationError):
                oe._ps(oe._GPU_BAR_QUERY)
        run.assert_not_called()

    def test_export_has_state_but_no_gpu_bar_or_raw_sizes(self):
        sizes = (16 * MIB + 7, 8 * 1024 ** 3 + 11)

        def fake_ps(code, timeout=22):
            if 'Win32_DeviceMemoryAddress' in code:
                return _bar(*sizes)
            return None
        with mock.patch.object(oe, '_is_windows', return_value=True), \
                mock.patch.object(oe, '_ps', side_effect=fake_ps), \
                mock.patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')):
            report = oe.inspect_pc()
        self.assertIn('gpu_bar', report['hardware'])
        self.assertNotIn('gpu_bar', oe._EXPORT_COLUMNS)
        data = oe.exportable_report(report)
        self.assertNotIn('gpu_bar', data['hardware'])
        self.assertEqual(data['bios_guidance']['rebar'], bg.REBAR_UNKNOWN)
        with tempfile.TemporaryDirectory() as folder:
            target = oe.export_snapshot(report, Path(folder) / 'diag.json')
            text = target.read_text(encoding='utf-8')
        self.assertNotIn('gpu_bar', text)
        self.assertNotIn('Sizes', text)
        for size in sizes:
            self.assertNotIn(str(size), text)
        self.assertIn('rebar', text)


class UiWiringTests(unittest.TestCase):
    """Roda mesmo sem Tk: confere a ligação do botão pelo código-fonte."""

    def _function(self, name):
        import ast
        tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
        return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)

    def test_button_starts_disabled_and_scan_enables_it(self):
        import ast
        build = ast.unparse(self._function('_build_diagnostics'))
        self.assertIn("text='Ver passo a passo'", build)
        self.assertIn("self.btn_bios_steps.configure(state='disabled')", build)
        scan = ast.unparse(self._function('_scan_finished'))
        self.assertIn("self.btn_bios_steps.configure(state='normal')", scan)

    def test_window_has_no_timer_link_or_download(self):
        import ast
        code = ast.unparse(self._function('show_bios_steps'))
        self.assertIn('bios_steps_text', code)
        self.assertIn('Toplevel', code)
        for forbidden in ('after', 'webbrowser', 'http', 'urlopen', 'startfile', 'subprocess'):
            self.assertNotIn(forbidden, code)


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def pack(self, *args, **kwargs):
        return None

    def configure(self, *args, **kwargs):
        return None

    def yview(self, *args):
        return None

    def set(self, *args):
        return None


class _FakeToplevel(_FakeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alive = True
        self.destroyed = 0

    def title(self, *args):
        return None

    def winfo_exists(self):
        return self.alive

    def destroy(self):
        self.destroyed += 1
        self.alive = False


class _FakeButton(_FakeWidget):
    created = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _FakeButton.created.append(self)


class ShowBiosStepsWithoutTkTests(unittest.TestCase):
    """R-18 sem Tk: executa show_bios_steps (lido com ast) com tk/ttk falsos."""

    def setUp(self):
        import ast
        import types
        tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'show_bios_steps')
        module = ast.Module(body=[node], type_ignores=[])
        _FakeButton.created = []
        fake_tk = types.SimpleNamespace(Toplevel=_FakeToplevel, Frame=_FakeWidget, Text=_FakeWidget)
        fake_ttk = types.SimpleNamespace(Scrollbar=_FakeWidget, Button=_FakeButton)
        namespace = {'tk': fake_tk, 'ttk': fake_ttk, 'BG': '#000', 'PANEL': '#111', 'TEXT': '#fff',
                     'bios_steps_text': bg.bios_steps_text}
        exec(compile(module, 'optimization_ui.py', 'exec'), namespace)
        self.show = namespace['show_bios_steps']
        self.panel = types.SimpleNamespace(report={'bios_guidance': {}}, _write=lambda *a: None)

    def test_opening_again_closes_previous(self):
        first = self.show(self.panel)
        second = self.show(self.panel)
        self.assertIsNot(first, second)
        self.assertEqual(first.destroyed, 1)
        self.assertEqual(second.destroyed, 0)
        self.assertIs(self.panel._bios_steps_window, second)

    def test_previous_already_closed_is_not_destroyed_again(self):
        first = self.show(self.panel)
        first.alive = False
        second = self.show(self.panel)
        self.assertEqual(first.destroyed, 0)
        self.assertIs(self.panel._bios_steps_window, second)

    def test_close_button_destroys_window(self):
        window = self.show(self.panel)
        close = [b for b in _FakeButton.created if b.kwargs.get('text') == 'Fechar']
        self.assertEqual(len(close), 1)
        close[0].kwargs['command']()
        self.assertEqual(window.destroyed, 1)
        self.assertFalse(window.winfo_exists())


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class StepsButtonTests(unittest.TestCase):
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
        self.panel = ou.OptimizationPanel(self.root, app_dir=self.tmp, state_dir=self.tmp,
                                          ask=lambda *a: False, show=lambda *a: None)
        self.panel.pack()
        # P3-04 (ressalva 1 da PR #200): o histórico de medições é lido num Job ao abrir;
        # espera ele terminar para a conferência de timers começar do zero.
        deadline = time.monotonic() + 5
        while self.panel._history_job is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.panel._history_job)

    def _report(self):
        hardware = _hardware(_bar(8 * 1024 ** 3))
        return {'hardware': hardware, 'power': {}, 'checks': [], 'errors': [], 'unmeasured': [],
                'profile': {'form_factor': 'desktop'},
                'bios_guidance': bg.build_bios_guidance(hardware, {'form_factor': 'desktop'})}

    def test_button_disabled_before_and_enabled_after_scan(self):
        button = self.panel.btn_bios_steps
        self.assertEqual(button.cget('text'), 'Ver passo a passo')
        self.assertTrue(button.instate(['disabled']))
        report = self._report()
        with mock.patch.object(self.panel, 'load_plans', lambda: None):
            self.panel._scan_finished(report)
        self.assertFalse(button.instate(['disabled']))
        text = self.panel.report_text.get('1.0', 'end')
        self.assertIn('BIOS — SÓ ORIENTAÇÃO', text)
        self.assertIn('Resizable BAR: não confirmado', text)
        self.assertIn(bg.REBAR_REASON_BIG, text)

    def test_window_is_read_only_text_and_closes_without_timer(self):
        report = self._report()
        report['bios_guidance']['steps'] = ['Baixe em http://exemplo']
        with mock.patch.object(self.panel, 'load_plans', lambda: None):
            self.panel._scan_finished(report)
        before = self.root.tk.call('after', 'info')
        window = self.panel.show_bios_steps()
        self.assertIsInstance(window, tk.Toplevel)
        texts = [w for w in window.winfo_children() if isinstance(w, tk.Text)]
        texts += [g for w in window.winfo_children() for g in w.winfo_children() if isinstance(g, tk.Text)]
        self.assertEqual(len(texts), 1)
        self.assertEqual(str(texts[0].cget('state')), 'disabled')
        content = texts[0].get('1.0', 'end')
        self.assertIn(bg.NEVER_CHANGES, content)
        self.assertIn('AI Tweaker', content)
        self.assertNotIn('http', content)
        window.destroy()
        self.root.update()
        self.assertEqual(self.root.tk.call('after', 'info'), before)

    def test_opening_again_closes_previous_window(self):
        with mock.patch.object(self.panel, 'load_plans', lambda: None):
            self.panel._scan_finished(self._report())
        first = self.panel.show_bios_steps()
        second = self.panel.show_bios_steps()
        self.root.update()
        self.assertEqual(first.winfo_exists(), 0)
        self.assertEqual(second.winfo_exists(), 1)
        self.assertIs(self.panel._bios_steps_window, second)
        second.destroy()

    def test_close_button_closes_window(self):
        from tkinter import ttk
        with mock.patch.object(self.panel, 'load_plans', lambda: None):
            self.panel._scan_finished(self._report())
        window = self.panel.show_bios_steps()
        buttons = [w for w in window.winfo_children()
                   if isinstance(w, ttk.Button) and w.cget('text') == 'Fechar']
        self.assertEqual(len(buttons), 1)
        buttons[0].invoke()
        self.root.update()
        self.assertEqual(window.winfo_exists(), 0)

    def test_without_report_does_nothing(self):
        self.assertIsNone(self.panel.show_bios_steps())


if __name__ == '__main__':
    unittest.main()
