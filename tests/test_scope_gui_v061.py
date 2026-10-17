"""Tk integration: the user's exact complaint, C-only shows C-only."""
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from deep_discovery_ui import show_deep_discovery


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class SelectedRootGuiTests(unittest.TestCase):
    def test_c_only_has_no_other_drive_tab_or_registry_record(self):
        parent = tk.Tk()
        parent.withdraw()
        self.addCleanup(parent.destroy)
        parent.dest = tk.StringVar(value='G:/backup')
        parent.catalog_items = {}
        parent.choices = {}
        parent.cleanup_candidates = set()
        parent.deep_scan_running = False
        parent.deep_scan_report = dict(schema='pcro-discovery-v1', records=[], roots=[],
                                        errors=[], skipped=[], apps=[], volume_stats={})
        parent._on_change = lambda: None
        parent.navigate = lambda target: None
        parent.refresh_catalog = lambda: None
        sample = dict(schema='pcro-discovery-v1',status='concluida', roots=['C:/'], directories=40, files=65,
                      errors=[], skipped=[], unassociated_executables=[], apps=[],
                      volume_stats={'C:': {'files': 65, 'directories': 40}, 'D:': {'files': 7, 'directories': 8}},
                      records=[dict(app_id='osu', app='osu!', path='C:/osu/Songs', kind='Músicas e beatmaps',
                                    evidence='C test', confidence='candidato', edition='stable'),
                               dict(app_id='steam', app='Steam', path='D:/SteamLibrary', kind='Pasta da instalação',
                                    evidence='D test', confidence='candidato', edition=None)])
        with patch('deep_discovery_ui.local_drives', return_value=['C:/', 'D:/']), \
             patch('deep_discovery_ui.discover_apps', return_value=[]), \
             patch('deep_discovery_ui.collect', return_value={'shortcuts': [], 'packages': [], 'errors': []}), \
             patch('deep_discovery_ui.find_app_data', return_value=[]), \
             patch('deep_discovery_ui.scan', return_value=sample) as fake_scan, \
             patch('deep_discovery_ui.known_save_roots', return_value={}), \
             patch('deep_discovery_ui.find_game_saves', return_value=[]), \
             patch('deep_discovery_ui.atomic_json'):
            show_deep_discovery(parent)
            win = next(x for x in parent.winfo_children() if isinstance(x, tk.Toplevel))
            checks = [x for x in descendants(win) if isinstance(x, ttk.Checkbutton)]
            self.assertEqual(len(checks), 2)
            checks[1].invoke()  # D goes from selected to unselected
            start = next(x for x in descendants(win) if isinstance(x, ttk.Button)
                         and x.cget('text') == 'Examinar unidades marcadas')
            start.invoke()
            completed = []
            def poll():
                if not parent.deep_scan_running and hasattr(parent, 'deep_scan_report'):
                    completed.append(True)
                    parent.quit()
                else:
                    parent.after(15, poll)
            parent.after(15, poll)
            parent.after(3500, parent.quit)
            parent.mainloop()
            self.assertTrue(completed, 'scan did not complete')
            self.assertEqual(fake_scan.call_args.args[1], ['C:/'])
            self.assertEqual([x['path'] for x in parent.deep_scan_report['records']], ['C:/osu/Songs'])
            tabs = next(x for x in descendants(win) if isinstance(x, ttk.Notebook))
            self.assertEqual(len(tabs.tabs()), 2)
            self.assertTrue(tabs.tab(tabs.tabs()[0], 'text').startswith('C:'))
            self.assertIn('não examinado', tabs.tab(tabs.tabs()[1], 'text'))
            self.assertEqual(set(parent.deep_scan_report['volume_stats']), {'C:'})

if __name__ == '__main__':
    unittest.main()

