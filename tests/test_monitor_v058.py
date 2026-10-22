"""Regression tests: real samples only, no fake temperature or Windows changes."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

import optimization_monitor as om
from tk_helpers import track_tk_root

LOG='''00,2026-10-15 20:00:00,Hardware monitoring log v1.6
01,2026-10-15 20:00:00,NVIDIA GeForce RTX 5070
02,2026-10-15 20:00:00,GPU temperature,GPU usage,CPU temperature,CPU usage,Framerate,Frametime,GPU power,Memory usage
03,2026-10-15 20:00:00,°C,%,°C,%,FPS,ms,W,MB
80,2026-10-15 20:00:01,48,12,53,25,120,8.33,80,1000
80,2026-10-15 20:00:02,64,93,72,46,146,6.85,220,2000
'''

class MonitorParser(unittest.TestCase):
    def test_afterburner_last_row_not_metadata(self):
        data,token=om.parse_hml_text(LOG)
        self.assertEqual(data['cpu_temp_c'],72)
        self.assertEqual(data['gpu_temp_c'],64)
        self.assertEqual(data['gpu_usage_pct'],93)
        self.assertEqual(data['fps_sampled'],146)
        self.assertEqual(data['gpu_power_w'],220)
        self.assertTrue(token.startswith('80,'))
    def test_ab_hml_semicolon_and_missing_sensors(self):
        raw='02;date;GPU1 temperature;CPU Package;Framerate\n80;date;68;75;160'
        x,_=om.parse_hml_text(raw)
        self.assertEqual(x['gpu_temp_c'],68)
        self.assertEqual(x['cpu_temp_c'],75)
        self.assertNotIn('gpu_power_w',x)
    def test_unknown_cpu_not_invented_and_bad_numbers_rejected(self):
        raw='02,date,GPU temperature,GPU power,Framerate\n80,date,275,N/A,NaN'
        x,_=om.parse_hml_text(raw)
        self.assertEqual(x,{})
    def test_nvidia_format_and_na(self):
        self.assertEqual(om.parse_nvidia_csv('59, 85, 182.34, 4034'),
                         {'gpu_temp_c':59.0,'gpu_usage_pct':85.0,'gpu_power_w':182.34,'vram_used_mb':4034.0})
        x=om.parse_nvidia_csv('N/A, 50, N/A, 3000')
        self.assertNotIn('gpu_temp_c',x)
        self.assertEqual(x['gpu_usage_pct'],50)
    def test_combine_prefers_direct_nvidia_gpu(self):
        x=om.combine({'gpu_temp_c':58}, {'gpu_temp_c':66,'cpu_temp_c':68})
        self.assertEqual(x['gpu_temp_c'],58)
        self.assertEqual(x['cpu_temp_c'],68)
    def test_reject_missing_hml_header(self):
        with self.assertRaises(ValueError):
            om.parse_hml_text('80,date,55')
    def test_reads_log_without_requiring_conversion(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'monitor.hml';f.write_text(LOG)
            x,t=om.read_afterburner_log(f)
            self.assertEqual(x['fps_sampled'],146)
            self.assertEqual(t[0],f.stat().st_size)
    def test_reads_large_log_tail(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'monitor.hml'
            f.write_text('02,date,CPU temperature,GPU temperature\n'+
                         ('80,dt,65,55\n'*100000)+'80,now,80,72\n')
            x,_=om.read_afterburner_log(f)
            self.assertEqual(x['cpu_temp_c'],80)
    def test_old_stale_log_needs_active_afterburner(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'old.hml';f.write_text(LOG)
            old=time.time()-60
            os.utime(f,(old,old))
            self.assertGreater(time.time()-f.stat().st_mtime,12)
    def test_session_and_summary_no_1percentile_conflation(self):
        s=om.new_session('CS2 mesmo mapa','antes')
        om.append_sample(s,{'cpu_temp_c':70,'fps_sampled':100},['Afterburner'],now='fixed')
        om.append_sample(s,{'cpu_temp_c':80,'fps_sampled':120},['Afterburner'],now='fixed2')
        with tempfile.TemporaryDirectory() as td:
            j,c=om.finish_session(s,td)
            saved=json.loads(j.read_text())
            self.assertEqual(saved['summary']['cpu_temp_c']['mean'],75)
            self.assertEqual(saved['summary']['fps_sampled']['mean'],110)
            self.assertNotIn('low_1',saved['summary'])
            self.assertTrue(c.is_file())
            self.assertIn('fps_sampled',c.read_text(encoding='utf-8-sig'))
            cmp=om.session_comparison(td,'CS2 mesmo mapa')
            self.assertEqual(cmp['count']['antes'],1)
            self.assertEqual(cmp['count']['depois'],0)
    def test_nvidia_read_only_and_fallback(self):
        with patch('optimization_monitor.os.name','nt'),\
             patch('optimization_monitor._nvidia_executable',return_value='nvidia-smi.exe'),\
             patch('optimization_monitor.subprocess.run') as runner:
            runner.return_value=MagicMock(returncode=0,stdout='58, 88, 240, 5000\n')
            x,err=om.poll_nvidia()
            self.assertIsNone(err)
            self.assertEqual(x['gpu_power_w'],240)
            command=runner.call_args.args[0]
            self.assertEqual(command[0],'nvidia-smi.exe')
            self.assertTrue(all('set' not in s for s in command))

class MonitorSessionFlow(unittest.TestCase):
    def test_live_worker_records_actual_available_metrics_only(self):
        import tkinter as tk
        from unittest.mock import patch
        from app import App
        try:
            with patch('app.App.refresh_catalog',lambda self:None):
                root=App()
                track_tk_root(self, root)
        except tk.TclError:
            self.skipTest('Sem servidor gráfico');return
        try:
            p=root.optimizer_panel
            p.mon_session=om.new_session('Teste sensores','antes')
            p.mon_stop.clear()
            def one_poll():
                p.mon_stop.set()
                return {'gpu_temp_c':51,'gpu_usage_pct':70},None
            with patch('optimization_ui.poll_nvidia',side_effect=one_poll):
                p._monitor_worker('')
            self.assertEqual(len(p.mon_session['rows']),1)
            row=p.mon_session['rows'][0]
            self.assertEqual(row['metrics']['gpu_temp_c'],51)
            self.assertNotIn('cpu_temp_c',row['metrics'])
            self.assertEqual(row['source'],['NVIDIA'])
            p._drain_monitor()
            self.assertIn('CPU °C',p.monitor_text.get('1.0','end'))
            self.assertIn('indisponível',p.monitor_text.get('1.0','end'))
        finally:
            root.destroy()

    def test_launch_does_not_start_monitor_or_switch_plan(self):
        import tkinter as tk
        from app import App
        try:
            with patch('app.App.refresh_catalog',lambda self:None),\
                 patch('optimization_monitor.poll_nvidia') as poll:
                root=App()
                track_tk_root(self, root)
                root.update_idletasks()
                self.assertFalse(root.optimizer_panel.mon_running)
                self.assertIsNone(root.optimizer_panel.mon_session)
                poll.assert_not_called()
        except tk.TclError:
            self.skipTest('Sem servidor gráfico');return
        else:
            root.destroy()


if __name__=='__main__':
    unittest.main()
