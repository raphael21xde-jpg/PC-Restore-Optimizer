"""FIX-M3-T4: nome do plano de energia no diagnóstico e na medição antes/depois.

Só texto simulado (saídas do ``powercfg`` em português, com acento e com
caractere ilegível) e funções falsas: nenhum powercfg, PowerShell, WMI,
registro ou subprocess de verdade.
"""
import ast
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import optimization_engine as oe  # noqa: E402
import pc_measure as pm  # noqa: E402

BALANCED = '381b4222-f694-41f0-9685-ff5bb260df2e'
HIGH = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
SAVER = 'a1841308-3541-4fab-bc81-f71556f20b4a'
ULTIMATE = 'e9a42b02-d5df-448d-aa00-03f14749eb61'
CUSTOM = '12345678-aaaa-bbbb-cccc-1234567890ab'

LIST_PT = (
    'Esquemas de Energia Existentes (* Ativo)\n'
    '-----------------------------------\n'
    f'GUID do Esquema de Energia: {BALANCED}  (Equilibrado) *\n'
    f'GUID do Esquema de Energia: {HIGH}  (Alto desempenho)\n'
    f'GUID do Esquema de Energia: {ULTIMATE}  (Desempenho máximo)\n'
    f'GUID do Esquema de Energia: {CUSTOM}  (Meu plano de jogo)\n')
ACTIVE_PT = f'GUID do Esquema de Energia: {BALANCED}  (Equilibrado)'


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _raw(**over):
    data = {'Cpu': [0, 10, 20, 30], 'Free': 4_000_000, 'Total': 16_000_000, 'Procs': 180,
            'Startup': 7, 'Plan': None}
    data.update(over)
    return data


class _NoCommands(unittest.TestCase):
    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('_run', '_ps'):
            patcher = mock.patch.object(oe, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)


class ParseTests(_NoCommands):
    def test_list_pt_br_with_star_and_accent(self):
        plans = oe.parse_power_list(LIST_PT)
        self.assertEqual([p['guid'] for p in plans], [BALANCED, HIGH, ULTIMATE, CUSTOM])
        self.assertEqual(plans[0]['name'], 'Equilibrado')
        self.assertTrue(plans[0]['active'])
        self.assertFalse(plans[1]['active'])
        self.assertEqual(plans[2]['name'], 'Desempenho máximo')
        self.assertEqual(oe.power_plan_name(ULTIMATE, plans), 'Desempenho máximo')
        self.assertEqual(oe.power_plan_name(CUSTOM.upper(), plans), 'Meu plano de jogo')

    def test_list_without_plans_is_empty_list(self):
        self.assertEqual(oe.parse_power_list('nada aqui'), [])
        self.assertEqual(oe.parse_power_list(''), [])

    def test_available_power_plans_uses_parser(self):
        with mock.patch.object(oe, '_run', return_value=LIST_PT) as run:
            self.assertEqual(oe.available_power_plans(), oe.parse_power_list(LIST_PT))
        run.assert_called_once_with(['powercfg', '/list'])
        with mock.patch.object(oe, '_run', return_value='vazio'):
            with self.assertRaises(oe.OptimizationError):
                oe.available_power_plans()

    def test_garbled_name_on_standard_guid_uses_fixed_table(self):
        plans = oe.parse_power_list(f'GUID do Esquema de Energia: {ULTIMATE}  (Desempenho m\ufffdximo) *')
        self.assertEqual(oe.power_plan_name(ULTIMATE, plans), 'Desempenho máximo')
        self.assertEqual(oe.power_plan_name(SAVER, []), 'Economia de energia')
        self.assertEqual(oe.power_plan_name(HIGH, None), 'Alto desempenho')
        self.assertEqual(oe.power_plan_name(BALANCED, [{'guid': BALANCED}]), 'Equilibrado')

    def test_garbled_name_on_unknown_guid_is_none(self):
        plans = oe.parse_power_list(f'GUID do Esquema de Energia: {CUSTOM}  (Plano m\ufffdximo)')
        self.assertIsNone(oe.power_plan_name(CUSTOM, plans))
        self.assertIsNone(oe.power_plan_name(CUSTOM, []))
        self.assertIsNone(oe.power_plan_name(None, plans))
        self.assertIsNone(oe.power_plan_name('nao-e-guid', plans))

    def test_name_equal_to_guid_is_not_a_name(self):
        plans = oe.parse_power_list(f'GUID do Esquema de Energia: {CUSTOM}')
        self.assertIsNone(oe.power_plan_name(CUSTOM, plans))

    def test_getactivescheme_pt_br(self):
        self.assertEqual(oe.parse_active_scheme(ACTIVE_PT), (BALANCED, 'Equilibrado'))
        self.assertEqual(oe.parse_active_scheme('sem guid'), (None, None))
        with mock.patch.object(oe, '_run', return_value=ACTIVE_PT):
            self.assertEqual(oe.active_power_guid(), BALANCED)

    def test_active_power_plan_name_read_only(self):
        calls = []

        def fake(command, timeout=18):
            calls.append(command)
            return LIST_PT if command[1] == '/list' else (
                f'GUID do Esquema de Energia: {CUSTOM}  (Meu plano de jogo)')
        with mock.patch.object(oe, '_run', side_effect=fake):
            self.assertEqual(oe.active_power_plan_name(), 'Meu plano de jogo')
        self.assertEqual(sorted(c[1] for c in calls), ['/getactivescheme', '/list'])

    def test_active_power_plan_name_list_fails_uses_getactivescheme(self):
        def fake(command, timeout=18):
            if command[1] == '/list':
                raise oe.OptimizationError(r'C:\Users\Fulano')
            return f'GUID do Esquema de Energia: {CUSTOM}  (Meu plano)'
        with mock.patch.object(oe, '_run', side_effect=fake):
            self.assertEqual(oe.active_power_plan_name(), 'Meu plano')

    def test_active_power_plan_name_garbled_everywhere(self):
        def fake(command, timeout=18):
            return f'GUID do Esquema de Energia: {HIGH}  (Alto \ufffd) *'
        with mock.patch.object(oe, '_run', side_effect=fake):
            self.assertEqual(oe.active_power_plan_name(), 'Alto desempenho')


class InspectTests(_NoCommands):
    def test_inspect_saves_active_name_outside_export(self):
        plans = oe.parse_power_list(LIST_PT)
        with mock.patch.object(oe, '_is_windows', return_value=True), \
                mock.patch.object(oe, '_ps', return_value=None), \
                mock.patch.object(oe, 'available_power_plans', return_value=plans), \
                mock.patch.object(oe, 'active_power_guid', return_value=BALANCED):
            report = oe.inspect_pc()
        self.assertEqual(report['power']['active_guid'], BALANCED)
        self.assertEqual(report['power']['active_name'], 'Equilibrado')
        self.assertNotIn('active_name', repr(oe._EXPORT_COLUMNS))


class DiagnosisTextTests(unittest.TestCase):
    def test_name_and_guid(self):
        text = oe.power_plan_text({'active_guid': BALANCED, 'active_name': 'Equilibrado'})
        self.assertEqual(text, f'Equilibrado ({BALANCED})')

    def test_without_name_only_guid(self):
        self.assertEqual(oe.power_plan_text({'active_guid': CUSTOM}), CUSTOM)
        self.assertEqual(oe.power_plan_text({'active_guid': CUSTOM, 'active_name': 'x\ufffdy'}), CUSTOM)

    def test_old_report_without_active_name_uses_plans(self):
        power = {'active_guid': HIGH, 'plans': oe.parse_power_list(LIST_PT)}
        self.assertEqual(oe.power_plan_text(power), f'Alto desempenho ({HIGH})')

    def test_nothing_is_unavailable(self):
        self.assertEqual(oe.power_plan_text({}), 'indisponível')
        self.assertEqual(oe.power_plan_text(None), 'indisponível')

    def test_ui_uses_power_plan_text(self):
        source = (ROOT / 'optimization_ui.py').read_text(encoding='utf-8')
        self.assertIn("'Plano de energia: '+power_plan_text(", source)
        self.assertNotIn("str(plans.get('active_guid') or 'indisponível')", source)


class MeasureTests(_NoCommands):
    def test_plan_null_uses_fallback(self):
        result = pm.read_measure(lambda code: _raw(), plan_name=lambda: 'Equilibrado')
        self.assertEqual(result['power_plan'], 'Equilibrado')
        self.assertEqual(result['cpu'], 20)

    def test_wmi_name_wins_and_fallback_not_called(self):
        fallback = mock.Mock(side_effect=_forbidden)
        result = pm.read_measure(lambda code: _raw(Plan='Alto desempenho'), plan_name=fallback)
        self.assertEqual(result['power_plan'], 'Alto desempenho')
        fallback.assert_not_called()

    def test_fallback_error_is_none_and_others_continue(self):
        def boom():
            raise RuntimeError(r'C:\Users\Fulano\segredo')
        result = pm.read_measure(lambda code: _raw(), plan_name=boom)
        self.assertIsNone(result['power_plan'])
        self.assertEqual(result['processes'], 180)
        self.assertEqual(result['startup'], 7)

    def test_fallback_with_path_is_none(self):
        result = pm.read_measure(lambda code: _raw(), plan_name=lambda: r'C:\Users\Fulano\plano')
        self.assertIsNone(result['power_plan'])

    def test_garbled_name_is_none(self):
        result = pm.read_measure(lambda code: _raw(), plan_name=lambda: 'Equil\ufffdbrado')
        self.assertIsNone(result['power_plan'])
        self.assertIsNone(pm.parse_measure(_raw(Plan='m\ufffdximo'))['power_plan'])

    def test_default_fallback_is_lazy_engine_function(self):
        with mock.patch.object(oe, 'active_power_plan_name', return_value='Economia de energia') as fn:
            result = pm.read_measure(lambda code: _raw())
        fn.assert_called_once_with()
        self.assertEqual(result['power_plan'], 'Economia de energia')

    def test_default_fallback_without_windows_is_none(self):
        # _run proibido: o erro vira None e a medição segue.
        result = pm.read_measure(lambda code: _raw())
        self.assertIsNone(result['power_plan'])
        self.assertEqual(result['cpu'], 20)

    def test_nothing_at_all_still_fails_without_fallback(self):
        fallback = mock.Mock(side_effect=_forbidden)
        with self.assertRaises(pm.MeasureError):
            pm.read_measure(lambda code: None, plan_name=fallback)
        fallback.assert_not_called()


class SourceTests(unittest.TestCase):
    def _function(self, name):
        tree = ast.parse((ROOT / 'optimization_engine.py').read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.unparse(node)
        self.fail(name)

    def test_new_path_never_changes_plan(self):
        for name in ('parse_power_list', 'parse_active_scheme', 'power_plan_name',
                     'active_power_plan_name', 'power_plan_text', 'available_power_plans',
                     'active_power_guid'):
            code = self._function(name).lower()
            for forbidden in ('/setactive', "'/s'", '-setactive', '/change', '/import', '/delete'):
                self.assertNotIn(forbidden, code, name)
        measure = (ROOT / 'pc_measure.py').read_text(encoding='utf-8').lower()
        self.assertNotIn('setactive', measure)
        self.assertNotIn('powercfg /s', measure)

    def test_standard_table_only_four_guids(self):
        self.assertEqual(oe.STANDARD_POWER_PLANS, {
            BALANCED: 'Equilibrado', HIGH: 'Alto desempenho',
            SAVER: 'Economia de energia', ULTIMATE: 'Desempenho máximo'})


if __name__ == '__main__':
    unittest.main()
