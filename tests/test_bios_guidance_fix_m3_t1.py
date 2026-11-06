"""FIX-M3-T1: Resizable BAR nunca vira "provavelmente ligado" só pelo tamanho da janela.

Caso real: RTX 5070 (driver 621.01) mostra janela de 16 GiB no Windows e o painel da
NVIDIA diz "BAR redimensionável: Não". Só dados sintéticos: nenhum comando real,
nenhum PowerShell, registro ou WMI.
"""
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bios_guidance as bg  # noqa: E402
import optimization_engine as oe  # noqa: E402

MIB = 1024 ** 2
GIB = 1024 ** 3
RTX_5070 = {'Sizes': [16 * MIB, 16 * GIB, 32 * MIB]}


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _rebar_line(guidance):
    return next(line for line in bg.bios_guidance_lines(guidance) if 'Resizable BAR:' in line)


class Rtx5070Tests(unittest.TestCase):
    def test_rtx_5070_window_is_not_confirmed(self):
        for value in (RTX_5070, [RTX_5070],
                      json.loads('{"value": [{"Sizes": {"value": [16777216, 17179869184, 33554432], '
                                 '"Count": 3}}], "Count": 1}')):
            with self.subTest(value=value):
                self.assertEqual(bg.rebar_state(value), (bg.REBAR_UNKNOWN, bg.REBAR_REASON_BIG))

    def test_big_reason_wording(self):
        self.assertEqual(bg.REBAR_REASON_BIG,
                         'O Windows informa uma janela de memória maior que 256 MiB, mas isso sozinho não '
                         'confirma o Resizable BAR (há placas que mostram isso com ele desligado).')

    def test_on_state_no_longer_exists(self):
        self.assertFalse(hasattr(bg, 'REBAR_ON'))
        self.assertFalse(hasattr(bg, 'REBAR_REASON_ON'))
        self.assertEqual(set(bg.REBAR_LABELS), {bg.REBAR_UNKNOWN})


class NeverProbablyOnTests(unittest.TestCase):
    def test_no_size_combination_is_probably_on(self):
        sizes = (None, 16 * MIB, 256 * MIB, 256 * MIB + 1, 512 * MIB, 8 * GIB, 16 * GIB, 1024 ** 4)
        for first, second in itertools.product(sizes, repeat=2):
            for value in ({'Sizes': [first]}, [{'Sizes': [first]}, {'Sizes': [second]}],
                          [{'Sizes': [first, second]}]):
                with self.subTest(value=value):
                    state, reason = bg.rebar_state(value)
                    self.assertEqual(state, bg.REBAR_UNKNOWN)
                    guidance = bg.build_bios_guidance({'gpu_bar': value}, {})
                    line = _rebar_line(guidance)
                    self.assertEqual(line.strip(), 'Resizable BAR: não confirmado (veja abaixo como conferir).')
                    self.assertNotIn('ligado', line)
                    self.assertNotIn('desligad', line)
                    self.assertNotIn('desligad', reason.replace('com ele desligado', ''))

    def test_forged_old_report_shows_not_confirmed(self):
        for reason in ('O Windows informa, para cada placa de vídeo, uma janela de memória maior que 256 MiB; '
                       'isso costuma indicar Resizable BAR ligado.', bg.REBAR_REASON_BIG, None):
            with self.subTest(reason=reason):
                text = '\n'.join(bg.bios_guidance_lines({'rebar': 'provavelmente_ligado', 'rebar_reason': reason}))
                self.assertIn('Resizable BAR: não confirmado', text)
                self.assertNotIn('provavelmente ligado', text.split('Resizable BAR:')[1].split('\n')[0])
                self.assertNotIn('isso costuma indicar Resizable BAR ligado', text)

    def test_big_reason_is_accepted_on_screen(self):
        text = '\n'.join(bg.bios_guidance_lines({'rebar': bg.REBAR_UNKNOWN, 'rebar_reason': bg.REBAR_REASON_BIG}))
        self.assertIn(bg.REBAR_REASON_BIG, text)


class CheckStepsTests(unittest.TestCase):
    def test_three_steps_wording(self):
        self.assertEqual(len(bg.REBAR_CHECK_STEPS), 3)
        self.assertIn('Painel de controle da NVIDIA', bg.REBAR_CHECK_STEPS[0])
        self.assertIn('"BAR redimensionável"', bg.REBAR_CHECK_STEPS[0])
        self.assertIn('Smart Access Memory', bg.REBAR_CHECK_STEPS[1])
        self.assertIn('GPU-Z', bg.REBAR_CHECK_STEPS[2])

    def test_steps_on_screen_after_reason_and_in_steps_text(self):
        guidance = bg.build_bios_guidance({'gpu_bar': RTX_5070}, {'form_factor': 'desktop'})
        lines = bg.bios_guidance_lines(guidance)
        index = next(i for i, line in enumerate(lines) if 'Resizable BAR:' in line)
        self.assertEqual(lines[index + 1].strip(), bg.REBAR_REASON_BIG)
        self.assertEqual(lines[index + 2].strip(), 'Como conferir sem entrar na BIOS:')
        for offset, step in enumerate(bg.REBAR_CHECK_STEPS, 3):
            self.assertIn(step, lines[index + offset])
        steps_text = bg.bios_steps_text(guidance)
        self.assertIn('Como conferir sem entrar na BIOS:', steps_text)
        for step in bg.REBAR_CHECK_STEPS:
            self.assertIn(step, steps_text)
        for text in ('\n'.join(lines), steps_text):
            self.assertNotIn('http', text)
            self.assertNotIn('baixe', text.lower())

    def test_steps_text_for_every_family(self):
        for family in bg.FAMILY_LABELS:
            text = bg.bios_steps_text({'family': family})
            for step in bg.REBAR_CHECK_STEPS:
                self.assertIn(step, text)


class InspectPcTests(unittest.TestCase):
    def test_inspect_pc_exports_not_confirmed(self):
        def fake_ps(code, timeout=22):
            if 'Win32_DeviceMemoryAddress' in code:
                return [dict(RTX_5070)]
            return None
        with mock.patch.object(oe, '_is_windows', return_value=True), \
                mock.patch.object(oe, '_ps', side_effect=fake_ps), \
                mock.patch.object(oe, '_run', _forbidden), \
                mock.patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')), \
                mock.patch.object(subprocess, 'run', _forbidden):
            report = oe.inspect_pc()
        self.assertEqual(report['bios_guidance']['rebar'], 'nao_confirmado')
        self.assertEqual(report['bios_guidance']['rebar_reason'], bg.REBAR_REASON_BIG)
        data = oe.exportable_report(report)
        self.assertEqual(data['bios_guidance']['rebar'], 'nao_confirmado')
        with tempfile.TemporaryDirectory() as folder:
            text = oe.export_snapshot(report, Path(folder) / 'diag.json').read_text(encoding='utf-8')
        self.assertIn('"rebar": "nao_confirmado"', text)
        self.assertNotIn('provavelmente_ligado"', text.split('"rebar"')[1].split(',')[0])


if __name__ == '__main__':
    unittest.main()
