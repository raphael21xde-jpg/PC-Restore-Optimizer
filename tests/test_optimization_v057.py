import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import optimization_engine as oe
import optimization_bench as ob


class OptimizationEngineTest(unittest.TestCase):
    def test_non_windows_inspection_is_read_only(self):
        if oe.os.name != 'nt':
            report=oe.inspect_pc()
            self.assertEqual(report['status'],'leitura')
            self.assertFalse(report['windows'])
            self.assertTrue(report['errors'])

    def test_power_list_localized_output(self):
        response='Esquemas de energia existentes:\n* Plano de energia GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Equilibrado) *\n Plano GUID: a1841308-3541-4fab-bc81-f71556f20b4a  (Economia de energia)'
        with patch.object(oe,'_run',return_value=response):
            plans=oe.available_power_plans()
        self.assertEqual(len(plans),2)
        self.assertTrue(plans[0]['active'])
        self.assertEqual(plans[0]['guid'],oe.BALANCED_GUID)

    def test_power_cannot_apply_unknown_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(oe,'available_power_plans',return_value=[{'guid':oe.BALANCED_GUID}]), patch.object(oe,'_run') as runner:
                with self.assertRaises(oe.OptimizationError):
                    oe.safe_change_power_plan('11111111-1111-1111-1111-111111111111',Path(tmp)/'revert.json')
                runner.assert_not_called()

    def test_power_apply_then_revert(self):
        a='381b4222-f694-41f0-9685-ff5bb260df2e'
        b='a1841308-3541-4fab-bc81-f71556f20b4a'
        state={'current':a,'calls':[]}
        def execute(args,*_p,**_k):
            self.assertEqual(args[0:2],['powercfg','/setactive'])
            state['current']=args[2]
            state['calls'].append(args)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'journal.json'
            with patch.object(oe,'available_power_plans',return_value=[{'guid':a},{'guid':b}]), patch.object(oe,'active_power_guid',side_effect=lambda:state['current']), patch.object(oe,'_run',side_effect=execute):
                result=oe.safe_change_power_plan(b,path)
                self.assertEqual(result['previous'],a)
                self.assertTrue(result['changed'])
                self.assertEqual(state['current'],b)
                with self.assertRaises(oe.OptimizationError):
                    oe.safe_change_power_plan(a,path)
                oe.revert_power_plan(path)
                self.assertEqual(state['current'],a)
                self.assertEqual(json.loads(path.read_text())['status'],'reverted')
                self.assertEqual(len(state['calls']),2)

    def test_external_power_change_blocks_reversal(self):
        a='381b4222-f694-41f0-9685-ff5bb260df2e'
        b='a1841308-3541-4fab-bc81-f71556f20b4a'
        c='8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'j.json'
            path.write_text(json.dumps({'schema':'pcro-power-1','status':'applied','previous':a,'requested':b}))
            with patch.object(oe,'available_power_plans',return_value=[{'guid':a},{'guid':b}]), patch.object(oe,'active_power_guid',return_value=c), patch.object(oe,'_run') as runner:
                with self.assertRaises(oe.OptimizationError):
                    oe.revert_power_plan(path)
                runner.assert_not_called()

    def test_readonly_report_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'inspect.json'
            oe.export_snapshot({'a':1},output)
            self.assertEqual(json.loads(output.read_text())['a'],1)
            with self.assertRaises(oe.OptimizationError):
                oe.export_snapshot({},Path(tmp)/'inspect.txt')


class BenchmarkTest(unittest.TestCase):
    def test_parse_semicolon_portuguese_frametimes(self):
        content='Time;FrameTime (ms)\n'+'\n'.join(f'{i};{16+i%3},5' for i in range(70))
        result=ob.parse_benchmark_text(content)
        self.assertEqual(result['samples'],70)
        self.assertEqual(result['source'],'frametime_ms')
        self.assertGreater(result['avg_fps'],50)
        self.assertLess(result['low_02'],result['avg_fps'])

    def test_parse_fps_column(self):
        content='Frame,FPS,Extra\n'+'\n'.join(f'{i},{100+i%20},ok' for i in range(100))
        result=ob.parse_benchmark_text(content)
        self.assertGreater(result['avg_fps'],100)
        self.assertLessEqual(result['low_02'],result['low_1'])

    def test_reject_incomplete_invalid_csv(self):
        for sample in ('ms,cpu\n1,2','FPS\n100\n120','FPS\n'+'\n'.join('0' for _ in range(50))):
            with self.assertRaises(ValueError):
                ob.parse_benchmark_text(sample)

    def test_wrong_unit_microseconds_rejected(self):
        value='Time,FrameTime (ms)\n'+'\n'.join(f'{i},16000' for i in range(100))
        with self.assertRaises(ValueError):
            ob.parse_benchmark_text(value)

    def test_median_three_repeats_comparison(self):
        before={'avg_fps':100,'low_1':50,'low_02':30}
        after={'avg_fps':120,'low_1':60,'low_02':36}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'runs.json'
            for phase,metrics in [('antes',before),('depois',after)]:
                for _ in range(3):
                    ob.insert_run(path,'CS2 cenário fixo',phase,metrics)
            s=ob.summarize(ob.read_history(path),'CS2 cenário fixo')
            self.assertTrue(s['sufficient_repeats'])
            self.assertEqual(s['delta_pct']['avg_fps'],20)
            self.assertEqual(s['count']['antes'],3)

    def test_scenario_not_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'runs.json'
            ob.insert_run(path,'CS2','antes',{'avg_fps':90,'low_1':40,'low_02':20})
            data=ob.read_history(path)
            s=ob.summarize(data,'Outros')
            self.assertEqual(s['count']['antes'],0)

    def test_csv_file_reject_huge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'large.csv'
            with path.open('wb') as handle:
                handle.truncate(25_000_001)
            with self.assertRaises(ValueError):
                ob.parse_csv_file(path)


if __name__=='__main__':
    unittest.main()
