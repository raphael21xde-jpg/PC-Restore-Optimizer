"""FIX-P3-06-02: ressalvas da revisão da PR #150 (BIOS só orientação).

Só dicts sintéticos: nenhum comando, nenhum registro, nenhum WMI e nenhum Tk.
"""
import pathlib
import re
import unittest

import bios_guidance as bg

_DEFAULT_OFF = bg._DEFAULT_REASONS[bg.XMP_OFF]
_FAMILIES = ('asus', 'msi', 'gigabyte', 'asrock', 'oem', 'desconhecido')


def _off_reason(configured, speed):
    return (f'A memória está configurada a {configured} MT/s e o módulo informa '
            f'{speed} MT/s. O perfil XMP/EXPO pode estar desligado, ou o '
            'processador/placa limita a velocidade.')


def _shown(reason, state=bg.XMP_OFF):
    return '\n'.join(bg.bios_guidance_lines({'xmp': state, 'xmp_reason': reason}))


class OffReasonNumbersTest(unittest.TestCase):
    def test_incoherent_numbers_fall_back_to_default(self):
        cases = {
            'configurada maior': (9999, 1),
            'configurada zero': (0, 3200),
            'iguais': (3200, 3200),
            'metade exata': (1600, 3200),
            'informada zero': (2133, 0),
        }
        for name, (configured, speed) in cases.items():
            with self.subTest(name):
                forged = _off_reason(configured, speed)
                text = _shown(forged)
                self.assertIn(_DEFAULT_OFF, text)
                self.assertNotIn(forged, text)
                self.assertNotIn(f'configurada a {configured} MT/s', text)

    def test_coherent_numbers_are_kept(self):
        reason = _off_reason(2133, 3200)
        text = _shown(reason)
        self.assertIn(reason, text)
        self.assertNotIn(_DEFAULT_OFF, text)

    def test_off_reason_ok_helper(self):
        self.assertTrue(bg._off_reason_ok(_off_reason(2400, 3200)))
        self.assertTrue(bg._off_reason_ok(_off_reason('2666.5', 3200)))
        self.assertFalse(bg._off_reason_ok(_off_reason(9999, 1)))
        self.assertFalse(bg._off_reason_ok(_off_reason(0, 3200)))
        self.assertFalse(bg._off_reason_ok(_off_reason(3200, 3200)))
        self.assertFalse(bg._off_reason_ok(_off_reason(1600, 3200)))
        self.assertFalse(bg._off_reason_ok('texto qualquer'))

    def test_bad_values_never_raise(self):
        for reason in (None, 12, ['x'], {'a': 1}, '', _off_reason('9' * 6, '9' * 6)):
            with self.subTest(reason=reason):
                text = _shown(reason)
                self.assertIn(_DEFAULT_OFF, text)
        self.assertFalse(bg._off_reason_ok(None))
        self.assertFalse(bg._off_reason_ok(3))

    def test_round_trip_from_xmp_state(self):
        ram = [{'Speed': 3200, 'ConfiguredClockSpeed': 2400},
               {'Speed': 3200, 'ConfiguredClockSpeed': 2400}]
        state, reason = bg.xmp_state(ram)
        self.assertEqual(state, bg.XMP_OFF)
        lines = bg.bios_guidance_lines({'xmp': state, 'xmp_reason': reason})
        self.assertEqual(_reason_after_label(lines), reason)
        self.assertEqual(sum(line.strip() == reason for line in lines), 1)

    def test_round_trip_from_build_bios_guidance(self):
        hardware = {'ram': [{'Speed': 3200, 'ConfiguredClockSpeed': 2400}]}
        guidance = bg.build_bios_guidance(hardware, {})
        lines = bg.bios_guidance_lines(guidance)
        reason = guidance['xmp_reason']
        self.assertEqual(_reason_after_label(lines), reason)
        self.assertEqual(sum(line.strip() == reason for line in lines), 1)


_XMP_LABEL = 'Perfil de memória (XMP/EXPO):'


def _reason_after_label(lines):
    """Acha a linha do perfil de memória pelo rótulo e devolve a seguinte (o motivo)."""
    for index, line in enumerate(lines):
        if line.strip().startswith(_XMP_LABEL):
            if index + 1 >= len(lines):
                raise AssertionError('linha do motivo não encontrada depois do rótulo')
            return lines[index + 1].strip()
    raise AssertionError('linha do perfil de memória não encontrada')


class FixP3_06_04Test(unittest.TestCase):
    def test_reason_after_label_missing_reason_fails_clearly(self):
        lines = ['Orientação da BIOS', _XMP_LABEL + ' Desligado']
        with self.assertRaisesRegex(AssertionError,
                                    'linha do motivo não encontrada depois do rótulo'):
            _reason_after_label(lines)

    def test_no_stale_rule_citations(self):
        source = pathlib.Path(bg.__file__).read_text(encoding='utf-8')
        citations = [m.start() for m in re.finditer('R-' + r'34\b', source)]
        stale = [pos for pos in citations
                 if not source[:pos].endswith('antiga ')]
        self.assertEqual(stale, [], 'citação solta da antiga R-34 em bios_guidance.py')


class PlainTermsTest(unittest.TestCase):
    def test_terms_are_explained_for_every_family(self):
        expected = ('UEFI (o nome atual da BIOS)',
                    'Above 4G Decoding (opção que deixa a placa de vídeo usar mais memória)',
                    'CSM (modo de compatibilidade antigo)',
                    'limpe a CMOS (volta a BIOS ao padrão de fábrica, pelo botão ou jumper '
                    'descrito no manual)')
        for family in _FAMILIES:
            with self.subTest(family=family):
                text = '\n'.join(bg.bios_guidance_lines({'family': family}))
                for term in expected:
                    self.assertIn(term, text)

    def test_docstrings_describe_off_rule(self):
        for doc in (bg.__doc__, bg.xmp_state.__doc__):
            self.assertIn('algum abaixo e nenhum acima', doc)
            self.assertIn('REASON_MIXED', doc)
            self.assertIn('REASON_UNITS', doc)


if __name__ == '__main__':
    unittest.main()
