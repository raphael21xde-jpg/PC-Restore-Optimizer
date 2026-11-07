"""FIX-M3-T7: XMP "provavelmente ligado" quando a RAM está acima do padrão JEDEC do tipo dela.

Só dicts sintéticos e um PowerShell simulado: nenhum comando real, nenhum
registro, nenhum WMI e nenhum Tk.
"""
import unittest
from unittest.mock import patch

import bios_guidance as bg
import optimization_engine as oe

_LINE_ON_STD = '  Perfil de memória (XMP/EXPO): provavelmente ligado (velocidade acima do padrão)'
_DEFAULT_ON_STD = 'A memória está configurada acima do padrão oficial (JEDEC) do tipo dela.'


def _above_reason(configured, kind, standard):
    return (f'A memória está configurada a {configured} MT/s, acima do padrão oficial (JEDEC) do '
            f'{kind}, que é {standard} MT/s. Isso costuma indicar o perfil XMP/EXPO ligado (ou um '
            'ajuste manual da memória).')


def _higher_note(speed):
    return (f' Um dos módulos informa uma velocidade maior ({speed} MT/s); o perfil pode estar ligado '
            'com um perfil mais lento, ou a memória foi ajustada à mão.')


def _modules(count, speed, configured, kind):
    module = {'Capacity': 8589934592, 'Speed': speed, 'ConfiguredClockSpeed': configured}
    if kind is not _MISSING:
        module['SMBIOSMemoryType'] = kind
    return [dict(module) for _ in range(count)]


_MISSING = object()


def _shown(guidance):
    return bg.bios_guidance_lines(guidance)


class AboveStandardStateTest(unittest.TestCase):
    def test_raphael_pc_ddr4_3600_is_probably_on(self):
        ram = _modules(4, 3600, 3600, 26)
        state, reason = bg.xmp_state(ram)
        self.assertEqual(state, bg.XMP_ON_STD)
        self.assertEqual(reason, _above_reason(3600, 'DDR4', 3200))
        lines = _shown(bg.build_bios_guidance({'ram': ram}, {}))
        self.assertIn(_LINE_ON_STD, lines)
        self.assertIn('    ' + _above_reason(3600, 'DDR4', 3200), lines)
        self.assertEqual(bg.XMP_LABELS[bg.XMP_ON_STD],
                         'provavelmente ligado (velocidade acima do padrão)')

    def test_at_standard_is_not_confirmed(self):
        self.assertEqual(bg.xmp_state(_modules(2, 3200, 3200, 26))[0], bg.XMP_UNKNOWN)

    def test_missing_configured_speed_is_not_confirmed(self):
        all_missing = [{'Speed': 3600, 'SMBIOSMemoryType': 26} for _ in range(2)]
        one_missing = _modules(1, 3600, 3600, 26) + [{'Speed': 3600, 'SMBIOSMemoryType': 26}]
        for name, ram in {'todos': all_missing, 'um': one_missing}.items():
            with self.subTest(name):
                self.assertEqual(bg.xmp_state(ram)[0], bg.XMP_UNKNOWN)

    def test_unknown_or_strange_type_is_not_confirmed(self):
        for kind in (0, 30, 35, _MISSING, '26', 'DDR4', True, False, 26.0, None):
            with self.subTest(kind=kind):
                self.assertEqual(bg.xmp_state(_modules(2, 3600, 3600, kind))[0], bg.XMP_UNKNOWN)

    def test_module_without_type_blocks_the_rule(self):
        ram = _modules(1, 3600, 3600, 26) + _modules(1, 3600, 3600, _MISSING)
        self.assertEqual(bg.xmp_state(ram)[0], bg.XMP_UNKNOWN)

    def test_mixed_types_is_not_confirmed(self):
        ram = _modules(1, 2400, 2400, 24) + _modules(1, 3600, 3600, 26)
        self.assertEqual(bg.xmp_state(ram)[0], bg.XMP_UNKNOWN)

    def test_module_at_standard_blocks_the_rule(self):
        ram = _modules(1, 3600, 3600, 26) + _modules(1, 3200, 3200, 26)
        self.assertEqual(bg.xmp_state(ram)[0], bg.XMP_UNKNOWN)

    def test_speed_does_not_change_the_state(self):
        # FIX-M3-T7-01: Speed maior não muda o estado; só completa o motivo.
        state, reason = bg.xmp_state(_modules(2, 4000, 3600, 26))
        self.assertEqual(state, bg.XMP_ON_STD)
        self.assertEqual(reason, _above_reason(3600, 'DDR4', 3200) + _higher_note(4000))

    def test_speed_equal_or_lower_adds_no_note(self):
        for speed in (3600, 3466, 2133, None):
            with self.subTest(speed=speed):
                self.assertEqual(bg.xmp_state(_modules(2, speed, 3600, 26)),
                                 (bg.XMP_ON_STD, _above_reason(3600, 'DDR4', 3200)))

    def test_lowest_configured_speed_goes_in_the_text(self):
        ram = _modules(1, 3600, 3600, 26) + _modules(1, 3466, 3466, 26)
        self.assertEqual(bg.xmp_state(ram), (bg.XMP_ON_STD, _above_reason(3466, 'DDR4', 3200)))

    def test_exact_half_still_wins(self):
        self.assertEqual(bg.xmp_state(_modules(2, 3200, 1600, 26)), (bg.XMP_UNKNOWN, bg.REASON_UNITS))

    def test_more_than_double_is_ignored(self):
        state, reason = bg.xmp_state(_modules(2, 7000, 7000, 26))
        self.assertEqual(state, bg.XMP_UNKNOWN)
        self.assertNotIn('JEDEC', reason)

    def test_ddr5_6000_is_not_confirmed(self):
        self.assertEqual(bg.xmp_state(_modules(2, 6000, 6000, 34))[0], bg.XMP_UNKNOWN)

    def test_ddr3_2400_is_probably_on(self):
        self.assertEqual(bg.xmp_state(_modules(2, 2400, 2400, 24)),
                         (bg.XMP_ON_STD, _above_reason(2400, 'DDR3', 2133)))

    def test_old_rules_unchanged(self):
        self.assertEqual(bg.xmp_state(_modules(2, 2133, 3200, _MISSING))[0], bg.XMP_ON)
        self.assertEqual(bg.xmp_state(_modules(2, 3200, 2133, _MISSING))[0], bg.XMP_OFF)
        self.assertEqual(bg.xmp_state([])[0], bg.XMP_UNKNOWN)


class AboveStandardScreenTest(unittest.TestCase):
    def test_round_trip_through_lines(self):
        guidance = bg.build_bios_guidance({'ram': _modules(4, 3600, 3600, 26)}, {})
        self.assertEqual(guidance['xmp'], bg.XMP_ON_STD)
        lines = _shown(dict(guidance))
        self.assertIn(_LINE_ON_STD, lines)
        self.assertIn('    ' + guidance['xmp_reason'], lines)

    def test_forged_reason_falls_back_to_default(self):
        cases = {
            'número no padrão': _above_reason(3200, 'DDR4', 3200),
            'número abaixo': _above_reason(2400, 'DDR4', 3200),
            'mais que o dobro': _above_reason(7000, 'DDR4', 3200),
            'padrão errado': _above_reason(3600, 'DDR4', 3000),
            'tipo errado': _above_reason(3600, 'DDR5', 3200),
            'tipo fora da tabela': _above_reason(3600, 'LPDDR4', 3200),
            'texto qualquer': 'Clique aqui e baixe a BIOS nova.',
        }
        for name, forged in cases.items():
            with self.subTest(name):
                lines = _shown({'xmp': bg.XMP_ON_STD, 'xmp_reason': forged})
                self.assertIn(_LINE_ON_STD, lines)
                self.assertIn('    ' + _DEFAULT_ON_STD, lines)
                self.assertNotIn('    ' + forged, lines)

    def test_above_reason_only_for_its_state(self):
        reason = _above_reason(3600, 'DDR4', 3200)
        for state in (bg.XMP_ON, bg.XMP_OFF, bg.XMP_UNKNOWN):
            with self.subTest(state=state):
                lines = _shown({'xmp': state, 'xmp_reason': reason})
                self.assertNotIn('    ' + reason, lines)
                self.assertIn('    ' + bg._DEFAULT_REASONS[state], lines)

    def test_default_reason_accepted(self):
        lines = _shown({'xmp': bg.XMP_ON_STD, 'xmp_reason': _DEFAULT_ON_STD})
        self.assertIn('    ' + _DEFAULT_ON_STD, lines)
        self.assertEqual(bg._DEFAULT_REASONS[bg.XMP_ON_STD], _DEFAULT_ON_STD)

    def test_old_on_state_still_shown(self):
        lines = _shown({'xmp': bg.XMP_ON, 'xmp_reason': bg._DEFAULT_REASONS[bg.XMP_ON]})
        self.assertIn('  Perfil de memória (XMP/EXPO): provavelmente ligado', lines)
        self.assertIn('    ' + bg._DEFAULT_REASONS[bg.XMP_ON], lines)


class MemoryTypeColumnTest(unittest.TestCase):
    def test_ram_query_reads_memory_type(self):
        calls = []

        def fake_ps(code, timeout=22):
            calls.append(code)
            return None

        with patch.object(oe, '_is_windows', return_value=True), \
                patch.object(oe, '_ps', side_effect=fake_ps), \
                patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')):
            oe.inspect_pc()
        ram = [code for code in calls if 'Win32_PhysicalMemory' in code]
        self.assertEqual(len(ram), 1)
        self.assertIn('SMBIOSMemoryType', ram[0])

    def test_memory_type_is_exported(self):
        self.assertIn('SMBIOSMemoryType', oe._EXPORT_COLUMNS['ram'])


class HigherSpeedNoteTest(unittest.TestCase):
    """FIX-M3-T7-01: módulo informa Speed maior que a configurada (ressalva 1 da PR #223)."""

    def test_highest_reported_speed_goes_in_the_note(self):
        ram = _modules(1, 4000, 3600, 26) + _modules(1, 4400, 3600, 26) + _modules(2, 3600, 3600, 26)
        self.assertEqual(bg.xmp_state(ram),
                         (bg.XMP_ON_STD, _above_reason(3600, 'DDR4', 3200) + _higher_note(4400)))

    def test_note_agrees_with_the_ram_check(self):
        # O check do diagnóstico ("confirmar XMP") e o motivo dizem a mesma coisa.
        ram = _modules(4, 4000, 3600, 26)
        state, reason = bg.xmp_state(ram)
        self.assertEqual(state, bg.XMP_ON_STD)
        self.assertIn('4000 MT/s', reason)
        self.assertIn('velocidade maior', reason)

    def test_strange_reported_speed_adds_no_note(self):
        # Teto: informada acima de 2x o padrão (DDR4: 6400) é dado estranho.
        for speed in (999999, 6401):
            with self.subTest(speed=speed):
                ram = _modules(1, speed, 3600, 26) + _modules(1, 4000, 3600, 26)
                self.assertEqual(bg.xmp_state(ram),
                                 (bg.XMP_ON_STD, _above_reason(3600, 'DDR4', 3200)))

    def test_reported_speed_at_the_cap_is_accepted(self):
        reason = _above_reason(3600, 'DDR4', 3200) + _higher_note(6400)
        self.assertEqual(bg.xmp_state(_modules(2, 6400, 3600, 26)), (bg.XMP_ON_STD, reason))
        self.assertIn('    ' + reason, _shown({'xmp': bg.XMP_ON_STD, 'xmp_reason': reason}))

    def test_note_shown_on_screen(self):
        guidance = bg.build_bios_guidance({'ram': _modules(4, 4000, 3600, 26)}, {})
        lines = _shown(dict(guidance))
        self.assertIn(_LINE_ON_STD, lines)
        self.assertIn('    ' + _above_reason(3600, 'DDR4', 3200) + _higher_note(4000), lines)

    def test_forged_note_falls_back_to_default(self):
        base = _above_reason(3600, 'DDR4', 3200)
        cases = {
            'informada igual': base + _higher_note(3600),
            'informada menor': base + _higher_note(3400),
            'informada zero': base + _higher_note(0),
            'nota com texto a mais': base + _higher_note(4000) + ' Baixe a BIOS nova.',
            'nota alterada': base + _higher_note(4000).replace('à mão', 'em casa'),
            'nota sem o resto': _higher_note(4000).strip(),
            'nota em base forjada': _above_reason(3200, 'DDR4', 3200) + _higher_note(4000),
            'informada absurda': base + _higher_note(999999),
            'informada acima do dobro': base + _higher_note(6401),
        }
        for name, forged in cases.items():
            with self.subTest(name):
                lines = _shown({'xmp': bg.XMP_ON_STD, 'xmp_reason': forged})
                self.assertIn('    ' + _DEFAULT_ON_STD, lines)
                self.assertNotIn('    ' + forged, lines)

    def test_note_only_for_its_state(self):
        reason = _above_reason(3600, 'DDR4', 3200) + _higher_note(4000)
        for state in (bg.XMP_ON, bg.XMP_OFF, bg.XMP_UNKNOWN):
            with self.subTest(state=state):
                lines = _shown({'xmp': state, 'xmp_reason': reason})
                self.assertIn('    ' + bg._DEFAULT_REASONS[state], lines)


class InspectEndToEndTest(unittest.TestCase):
    """FIX-M3-T7-01 (ressalva 2 da PR #223): inspect_pc com PowerShell simulado."""

    def _inspect(self):
        ram = _modules(4, 3600, 3600, 26)

        def fake_ps(code, timeout=22):
            if 'Win32_PhysicalMemory' in code:
                return [dict(module) for module in ram]
            return None

        with patch.object(oe, '_is_windows', return_value=True), \
                patch.object(oe, '_ps', side_effect=fake_ps), \
                patch.object(oe, 'available_power_plans', side_effect=oe.OptimizationError('x')):
            return oe.inspect_pc()

    def test_four_ddr4_3600_modules_end_probably_on(self):
        report = self._inspect()
        self.assertEqual(report['bios_guidance']['xmp'], bg.XMP_ON_STD)
        self.assertEqual(report['bios_guidance']['xmp_reason'], _above_reason(3600, 'DDR4', 3200))

    def test_exported_json_keeps_memory_type(self):
        import json
        import tempfile
        from pathlib import Path
        report = self._inspect()
        with tempfile.TemporaryDirectory() as folder:
            path = oe.export_snapshot(report, Path(folder) / 'relatorio.json')
            saved = json.loads(path.read_text(encoding='utf-8'))
        ram = saved['hardware']['ram']
        self.assertEqual(len(ram), 4)
        self.assertTrue(all(module.get('SMBIOSMemoryType') == 26 for module in ram))
        self.assertEqual(saved['bios_guidance']['xmp'], bg.XMP_ON_STD)


if __name__ == '__main__':
    unittest.main()
