"""P3-02: medição antes e depois (pc_measure.py).

Só dados simulados e ``ps`` falso: nenhum PowerShell, registro, WMI, powercfg
ou subprocess de verdade. Arquivos só em TemporaryDirectory.
"""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import optimization_engine as oe  # noqa: E402
import pc_measure as pm  # noqa: E402

ENV = {'USERPROFILE': r'C:\Users\Fulano', 'USERNAME': 'Fulano', 'SystemRoot': r'C:\Windows'}


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _raw(**over):
    data = {'Cpu': [0, 10, 20, 30], 'Free': 4_000_000, 'Total': 16_000_000, 'Procs': 180,
            'Startup': 7, 'Plan': 'Equilibrado'}
    data.update(over)
    return data


def _entry(phase, values, at):
    return {'phase': phase, 'at': at.isoformat(), 'values': values}


BASE = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


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


class SourceTests(unittest.TestCase):
    def test_module_has_no_tk_and_no_direct_commands(self):
        tree = ast.parse((ROOT / 'pc_measure.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        for name in ('tkinter', 'subprocess', 'ctypes', 'winreg'):
            self.assertNotIn(name, imported)

    def test_query_is_read_only(self):
        query = pm.MEASURE_QUERY
        self.assertIn('Win32_PerfFormattedData_PerfOS_Processor', query)
        self.assertIn("Name='_Total'", query)
        self.assertIn('Win32_OperatingSystem', query)
        self.assertIn('FreePhysicalMemory', query)
        self.assertIn('TotalVisibleMemorySize', query)
        self.assertIn('Win32_Process', query)
        self.assertIn('Win32_PowerPlan', query)
        self.assertIn('IsActive', query)
        self.assertIn('Start-Sleep ' + str(pm.MEASURE_INTERVAL), query)
        self.assertEqual(pm.MEASURE_SAMPLES, 12)
        self.assertEqual(pm.MEASURE_INTERVAL, 5)
        for key in ('Run', 'RunOnce'):
            self.assertIn('CurrentVersion\\' + key, query)
        self.assertIn('HKCU:', query)
        self.assertIn('HKLM:', query)
        self.assertIn("GetFolderPath('Startup')", query)
        self.assertIn("GetFolderPath('CommonStartup')", query)
        lowered = query.lower()
        for forbidden in ('set-', 'remove-', 'new-', 'stop-', 'invoke-cimmethod', 'start-process',
                          'powercfg /s', 'powercfg -s', 'reg add', 'reg delete', 'runas', 'commandline',
                          'executablepath'):
            self.assertNotIn(forbidden, lowered)
        # Só contagem: os nomes dos programas da inicialização nunca saem da consulta.
        self.assertNotIn('Name=$prop.Name', query)


class ParseTests(unittest.TestCase):
    def test_full_data(self):
        result = pm.parse_measure(_raw())
        # A primeira amostra (aquecimento) é descartada: média de 10, 20 e 30.
        self.assertEqual(result, {'cpu': 20, 'memory': 75, 'processes': 180, 'startup': 7,
                                  'power_plan': 'Equilibrado'})

    def test_missing_or_unreadable_is_none_never_zero(self):
        for raw in (None, [], 'x', {}, {'value': []}):
            with self.subTest(raw=raw):
                self.assertEqual(pm.parse_measure(raw), {k: None for k in pm.METRICS})
        bad = _raw(Cpu=['a', None, -3, float('nan')], Free=None, Total=0, Procs=0, Startup=-1, Plan='  ')
        self.assertEqual(pm.parse_measure(bad), {k: None for k in pm.METRICS})
        bad = _raw(Free=True, Total=16, Procs=True, Startup=True, Plan=5)
        result = pm.parse_measure(bad)
        for key in ('memory', 'processes', 'startup', 'power_plan'):
            self.assertIsNone(result[key], key)
        self.assertIsNone(pm.parse_measure(_raw(Free=20, Total=10))['memory'])

    def test_cpu_all_zero_or_only_warmup_is_none(self):
        self.assertIsNone(pm.parse_measure(_raw(Cpu=[0, 0, 0]))['cpu'])
        self.assertIsNone(pm.parse_measure(_raw(Cpu=[50]))['cpu'])
        self.assertIsNone(pm.parse_measure(_raw(Cpu=50))['cpu'])
        self.assertIsNone(pm.parse_measure(_raw(Cpu=None))['cpu'])

    def test_startup_zero_is_real_zero(self):
        self.assertEqual(pm.parse_measure(_raw(Startup=0))['startup'], 0)

    def test_powershell_51_value_wrapper(self):
        self.assertEqual(pm.parse_measure({'value': [_raw()]})['processes'], 180)

    def test_plan_name_hides_user_name_and_is_short(self):
        result = pm.parse_measure(_raw(Plan='Plano do Fulano\x07' + 'x' * 200), ENV)
        self.assertNotIn('Fulano', result['power_plan'])
        self.assertNotIn('\x07', result['power_plan'])
        self.assertLessEqual(len(result['power_plan']), 90)


class ReadTests(_NoCommands):
    def test_read_uses_fake_ps(self):
        ps = mock.Mock(return_value=_raw())
        self.assertEqual(pm.read_measure(ps)['cpu'], 20)
        ps.assert_called_once_with(pm.MEASURE_QUERY)

    def test_read_failure_raises_generic_error(self):
        ps = mock.Mock(side_effect=RuntimeError(r'C:\Users\Fulano\segredo'))
        with self.assertRaises(pm.MeasureError) as ctx:
            pm.read_measure(ps)
        self.assertNotIn('Fulano', str(ctx.exception))
        self.assertEqual(str(ctx.exception), pm.MEASURE_FAILED)

    def test_read_with_no_data_at_all_raises(self):
        with self.assertRaises(pm.MeasureError):
            pm.read_measure(lambda code: None)

    def test_default_ps_is_lazy_and_patched(self):
        with mock.patch.object(oe, '_ps', return_value=_raw()) as ps:
            self.assertEqual(pm.read_measure()['processes'], 180)
        self.assertEqual(ps.call_args.kwargs.get('timeout'), pm.MEASURE_TIMEOUT)


class SaveTests(_NoCommands):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / pm.MEASURE_FILE

    def test_save_and_read(self):
        measure = pm.parse_measure(_raw())
        history = pm.save_measure(self.path, 'antes', measure)
        self.assertEqual(len(history['measures']), 1)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['schema'], pm.SCHEMA)
        entry = saved['measures'][0]
        self.assertEqual(entry['phase'], 'antes')
        self.assertEqual(entry['values'], measure)
        at = datetime.fromisoformat(entry['at'])
        self.assertEqual(at.utcoffset(), timedelta(0))
        self.assertEqual(pm.read_measures(self.path), saved)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))
        self.assertFalse(list(self.path.parent.glob('*.lock')))

    def test_invalid_phase_is_refused(self):
        with self.assertRaises(ValueError):
            pm.save_measure(self.path, 'durante', pm.parse_measure(_raw()))
        self.assertFalse(self.path.exists())

    def test_keeps_only_last_50(self):
        for i in range(55):
            pm.save_measure(self.path, 'antes', pm.parse_measure(_raw(Procs=100 + i)))
        measures = pm.read_measures(self.path)['measures']
        self.assertEqual(len(measures), pm.MAX_MEASURES)
        self.assertEqual(measures[0]['values']['processes'], 105)
        self.assertEqual(measures[-1]['values']['processes'], 154)

    def test_no_user_name_or_path_in_file(self):
        measure = pm.parse_measure(_raw(Plan=r'C:\Users\Fulano\plano'), ENV)
        measure['extra'] = r'C:\Users\Fulano\segredo'
        pm.save_measure(self.path, 'antes', measure)
        text = self.path.read_text(encoding='utf-8')
        self.assertNotIn('Fulano', text)
        self.assertNotIn('segredo', text)

    def test_unreadable_history_changes_nothing(self):
        self.path.write_text('{quebrado', encoding='utf-8')
        with self.assertRaises(ValueError):
            pm.save_measure(self.path, 'antes', pm.parse_measure(_raw()))
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{quebrado')
        self.path.write_text(json.dumps({'schema': 'outro', 'measures': []}), encoding='utf-8')
        with self.assertRaises(ValueError):
            pm.save_measure(self.path, 'antes', pm.parse_measure(_raw()))

    def test_lock_busy_changes_nothing(self):
        with mock.patch.object(pm, 'exclusive_lock', side_effect=TimeoutError('x')):
            with self.assertRaises(ValueError):
                pm.save_measure(self.path, 'antes', pm.parse_measure(_raw()))
        self.assertFalse(self.path.exists())

    def test_missing_file_reads_empty(self):
        self.assertEqual(pm.read_measures(self.path), {'schema': pm.SCHEMA, 'measures': []})


class CompareTests(unittest.TestCase):
    def _values(self, **over):
        values = {'cpu': 20, 'memory': 60, 'processes': 200, 'startup': 10, 'power_plan': 'Equilibrado'}
        values.update(over)
        return values

    def _text(self, measures):
        return '\n'.join(pm.compare_measures({'schema': pm.SCHEMA, 'measures': measures}))

    def test_both_sides(self):
        text = self._text([_entry('antes', self._values(), BASE),
                           _entry('depois', self._values(cpu=12, memory=55, processes=180, startup=7,
                                                         power_plan='Alto desempenho'),
                                  BASE + timedelta(hours=1))])
        self.assertIn('Uso do processador (média): 20% → 12% (8 pontos percentuais a menos)', text)
        self.assertIn('Memória em uso: 60% → 55% (5 pontos percentuais a menos)', text)
        self.assertIn('Processos abertos: 200 → 180 (20 a menos)', text)
        self.assertIn('Programas que abrem com o Windows: 10 → 7 (3 a menos)', text)
        self.assertIn('Plano de energia: Equilibrado → Alto desempenho (mudou)', text)
        self.assertIn(pm.MEASURE_WARNING, text)
        for word in ('melhor', 'pior', 'ganho'):
            self.assertNotIn(word, text.lower())

    def test_more_and_same(self):
        text = self._text([_entry('antes', self._values(), BASE),
                           _entry('depois', self._values(cpu=25, startup=10), BASE + timedelta(hours=1))])
        self.assertIn('20% → 25% (5 pontos percentuais a mais)', text)
        self.assertIn('10 → 10 (igual)', text)
        self.assertIn('Equilibrado → Equilibrado (igual)', text)

    def test_missing_metric_is_no_data(self):
        text = self._text([_entry('antes', self._values(cpu=None), BASE),
                           _entry('depois', self._values(memory=None), BASE + timedelta(hours=1))])
        self.assertIn('Uso do processador (média): sem dado', text)
        self.assertIn('Memória em uso: sem dado', text)
        self.assertNotIn('pontos percentuais a menos', text.split('Memória')[0].split('processador')[1])

    def test_uses_last_before_and_last_after_it(self):
        text = self._text([_entry('antes', self._values(processes=100), BASE),
                           _entry('depois', self._values(processes=110), BASE + timedelta(hours=1)),
                           _entry('antes', self._values(processes=300), BASE + timedelta(hours=2)),
                           _entry('depois', self._values(processes=250), BASE + timedelta(hours=3))])
        self.assertIn('Processos abertos: 300 → 250 (50 a menos)', text)

    def test_after_older_than_before_means_missing_after(self):
        text = self._text([_entry('depois', self._values(), BASE),
                           _entry('antes', self._values(), BASE + timedelta(hours=1))])
        self.assertIn(pm.MISSING_AFTER, text)
        self.assertNotIn('→', text)
        self.assertIn(pm.MEASURE_WARNING, text)

    def test_missing_before_or_everything(self):
        text = self._text([_entry('depois', self._values(), BASE)])
        self.assertIn(pm.MISSING_BEFORE, text)
        # Ressalva 5 da PR #200: já existe uma DEPOIS; falta só a ANTES.
        self.assertNotIn(pm.MISSING_AFTER, text)
        self.assertIn(pm.AFTER_NEEDS_BEFORE, text)
        text = self._text([])
        self.assertIn(pm.MISSING_BEFORE, text)
        self.assertIn(pm.MISSING_AFTER, text)
        self.assertIn('Medir ANTES (1 min)', pm.MISSING_BEFORE)
        self.assertIn('Medir DEPOIS (1 min)', pm.MISSING_AFTER)

    def test_garbage_history_never_breaks(self):
        for history in (None, [], 'x', {'measures': 'x'}, {'measures': [None, 1, {'phase': ['antes']},
                                                                         {'phase': 'antes', 'at': 'ontem'},
                                                                         {'phase': 'antes', 'at': 5}]}):
            with self.subTest(history=history):
                text = '\n'.join(pm.compare_measures(history))
                self.assertIn(pm.MISSING_BEFORE, text)

    def test_stored_values_are_checked_again(self):
        before = {'cpu': -5, 'memory': 'muito', 'processes': True, 'startup': [1], 'power_plan': {'a': 1}}
        after = {'cpu': 300, 'memory': 50, 'processes': 10, 'startup': 2, 'power_plan': r'C:\Users\Fulano'}
        text = self._text([_entry('antes', before, BASE), _entry('depois', after, BASE + timedelta(hours=1))])
        for label in ('Uso do processador (média)', 'Memória em uso', 'Processos abertos',
                      'Programas que abrem com o Windows', 'Plano de energia'):
            self.assertIn(label + ': sem dado', text)

    def test_one_point_is_singular_and_question_says_processes(self):
        text = self._text([_entry('antes', self._values(), BASE),
                           _entry('depois', self._values(cpu=19), BASE + timedelta(hours=1))])
        self.assertIn('20% → 19% (1 ponto percentual a menos)', text)
        # Ressalva 4 da PR #200: o que é contado são processos.
        self.assertIn('quantos processos estão abertos', pm.MEASURE_CONFIRMATION)
        self.assertNotIn('programas estão abertos', pm.MEASURE_CONFIRMATION)

    def test_naive_timestamp_is_ignored(self):
        text = self._text([{'phase': 'antes', 'at': '2026-11-06T12:00:00', 'values': self._values()}])
        self.assertIn(pm.MISSING_BEFORE, text)


if __name__ == '__main__':
    unittest.main()
