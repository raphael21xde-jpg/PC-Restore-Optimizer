import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stutter_analysis import analyze_file,parse_frames,analyze_frames,analyze_sampled_fps_session,correlate_with_session


class StutterAnalysisTests(unittest.TestCase):
    def _csv(self,folder,name,header,rows):
        path=Path(folder)/name
        with path.open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f);writer.writerow(header);writer.writerows(rows)
        return path

    def test_presentmon_v2_per_frame_real_stalls(self):
        with tempfile.TemporaryDirectory() as td:
            ms=[8.33]*500+[90]+[8.33]*500+[70]
            t=0;rows=[]
            for v in ms:
                t+=v/1000
                rows.append(['cs2.exe',hex(123),round(t,5),v])
            p=self._csv(td,'v2.csv',['Application','SwapChainAddress','TimeInSeconds','MsBetweenPresents'],rows)
            a=analyze_file(p)
            self.assertEqual(a['count'],1002)
            self.assertEqual(a['event_count'],2)
            self.assertEqual(a['worst_ms'],90)
            self.assertLess(a['low_1'],a['avg_fps'])
            self.assertLess(a['low_02'],a['low_1'])

    def test_filter_process_and_swapchain(self):
        with tempfile.TemporaryDirectory() as td:
            rows=[['cs2.exe','0xa',4.5] for _ in range(60)]
            rows += [['obs64.exe','0xb',120] for _ in range(60)]
            rows += [['cs2.exe','0xc',200] for _ in range(2)]
            p=self._csv(td,'mixed.csv',['Application','SwapChainAddress','MsBetweenPresents'],rows)
            a=analyze_file(p)
            self.assertEqual(a['count'],60)
            self.assertEqual(a['event_count'],0)
            with self.assertRaisesRegex(ValueError,'Não encontrei'):
                analyze_file(p,'valorant.exe')

    def test_presentmon_v23_ms_appstart(self):
        with tempfile.TemporaryDirectory() as td:
            rows=[[k*5.0,5.0] for k in range(120)]
            p=self._csv(td,'pm.csv',['TimeInMs','MsBetweenAppStart'],rows)
            frames,meta=parse_frames(p)
            self.assertEqual(meta['column'],'MsBetweenAppStart')
            self.assertAlmostEqual(frames[-1][0],.595,places=2)

    def test_import_fps_column_frames_and_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            p=self._csv(td,'fps.csv',['fps'],[[144] for _ in range(100)])
            a=analyze_file(p)
            self.assertAlmostEqual(a['avg_fps'],144,delta=0.01)
            self.assertEqual(a['event_count'],0)
            invalid=self._csv(td,'bad.csv',['temperature'],[[52] for _ in range(100)])
            with self.assertRaises(ValueError):analyze_file(invalid)

    def test_sensor_samples_show_spikes_but_not_lows(self):
        data={'schema':'pcro-monitor-1','rows':[
            {'timestamp':'a','metrics':{'fps_sampled':188.4}},
            {'timestamp':'b','metrics':{'fps_sampled':55.9,'cpu_temp_c':82.375,'cpu_usage_pct':98.5}},
            {'timestamp':'c','metrics':{'fps_sampled':1.8,'cpu_temp_c':85.375,'cpu_usage_pct':100}},
        ]}
        result=analyze_sampled_fps_session(data)
        self.assertEqual(len(result['drops']),2)
        self.assertEqual(result['drops'][0]['to_fps'],55.9)
        self.assertNotIn('low_1',result)

    def test_correlation_only_when_time_proven(self):
        r={'worst_events':[{'t_s':10,'ms':55}]}
        session={'rows':[{'timestamp':'2026-10-15T10:00:11+00:00',
                          'metrics':{'cpu_temp_c':84}}]}
        self.assertEqual(correlate_with_session(r,session),[])
        self.assertEqual(correlate_with_session(r,session,'2026-10-15T10:00:00+00:00')[0]['sensor_readings']['cpu_temp_c'],84)
        session['rows'][0]['timestamp']='2026-10-15T10:10:00+00:00'
        self.assertEqual(correlate_with_session(r,session,'2026-10-15T10:00:00+00:00'),[])

    def test_file_size_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'long.csv';p.write_text('FPS\n'+('150\n'*30))
            with patch('stutter_analysis.MAX_FILE_BYTES',10):
                with self.assertRaisesRegex(ValueError,'150 MB'):analyze_file(p)

    def test_app_starts_without_presentmon_or_capture(self):
        try:
            from app import App
            with patch('app.App.refresh_catalog',lambda self:None):root=App()
        except Exception as exc:
            import tkinter as tk
            if isinstance(exc,tk.TclError):self.skipTest('Sem interface X11')
            raise
        try:
            self.assertIsNone(root.optimizer_panel.capture_proc)
            self.assertIsNone(root.optimizer_panel.stutter_last)
            self.assertGreaterEqual(root.optimizer_panel.tabs.index('end'),6)
        finally:root.destroy()

if __name__=='__main__':unittest.main()
