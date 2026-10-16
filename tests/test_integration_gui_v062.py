"""GUI regression for the screen-recording reports in v0.6.1."""
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
import unittest
from unittest.mock import patch

from deep_discovery_ui import show_deep_discovery
from volume_paths import volume_of


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def fake_report(roots):
    letters = sorted({volume_of(root) for root in roots})
    return dict(schema='pcro-discovery-v1',status='concluida', roots=list(roots),
                records=[dict(app_id='g', app='Game', path=d+'/Game/Saves', kind='Game save',
                              evidence='mock',confidence='candidato',edition=None) for d in letters],
                apps=[dict(id='g',name='Game',category='Jogo')],
                volume_stats={d:{'directories': 5,'files':10} for d in letters},
                directories=len(letters)*5, files=len(letters)*10,
                errors=[],skipped=[],unassociated_executables=[])


class SequentialScanGUI(unittest.TestCase):
    def test_scanning_d_after_c_does_not_erase_c(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        root.dest = tk.StringVar(value='G:/backup')
        root.catalog_items = {}
        root.choices = {'C:/Save/previous': 'keep', 'D:/Save/new': 'keep'}
        root.cleanup_candidates = set()
        root.deep_scan_running = False
        root._on_change = lambda: None
        root.navigate = lambda target: None
        calls = []
        def scanner(apps, roots, **kwargs):
            calls.append(tuple(roots))
            return fake_report(roots)
        with patch('deep_discovery_ui.local_drives',return_value=['C:/','D:/','F:/','G:/']), \
             patch('deep_discovery_ui.scan',side_effect=scanner), \
             patch('deep_discovery_ui.discover_apps',return_value=[]), \
             patch('deep_discovery_ui.collect',return_value={'shortcuts':[], 'packages':[], 'errors':[]}), \
             patch('deep_discovery_ui.find_app_data',return_value=[]), \
             patch('deep_discovery_ui.atomic_json'):
            show_deep_discovery(root)
            win = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
            checks = [x for x in descendants(win) if isinstance(x,ttk.Checkbutton)]
            self.assertEqual(len(checks), 4)
            start = next(x for x in descendants(win) if isinstance(x,ttk.Button)
                         and x.cget('text')=='Examinar unidades marcadas')
            for ch in checks[1:]: ch.invoke()
            start.invoke()
            self._wait_for_scan(root)
            self.assertEqual({r['path'] for r in root.deep_scan_report['records']}, {'C:/Game/Saves'})
            self.assertEqual(calls, [('C:/',)])
            checks[0].invoke()
            checks[1].invoke()
            start.invoke()
            self._wait_for_scan(root)
            self.assertEqual(calls, [('C:/',), ('D:/',)])
            self.assertEqual({r['path'] for r in root.deep_scan_report['records']},
                             {'C:/Game/Saves','D:/Game/Saves'})
            self.assertEqual(root.choices, {'C:/Save/previous':'keep','D:/Save/new':'keep'})
            self.assertEqual(root.deep_scan_report['latest_scanned_drives'],['D:'])
            tabs = next(x for x in descendants(win) if isinstance(x,ttk.Notebook))
            self.assertEqual(len(tabs.tabs()), 4)
            labels = [tabs.tab(t,'text') for t in tabs.tabs()]
            self.assertTrue(any('C:' in s and 'salvo' in s for s in labels))
            self.assertTrue(any('D:' in s and 'atual' in s for s in labels))
            self.assertTrue(any('F:' in s and 'não examinado' in s for s in labels))

    @staticmethod
    def _wait_for_scan(root):
        def poll():
            if not root.deep_scan_running:
                root.quit()
            else:
                root.after(15, poll)
        root.after(15, poll)
        root.after(8000, root.quit)
        root.mainloop()
        if root.deep_scan_running:
            raise AssertionError('scan was not completed')


class CatalogPreservationGUI(unittest.TestCase):
    def test_catalog_app_selection_without_data_appears_in_preservation(self):
        from app import App
        with patch('app.App.refresh_catalog', lambda app: None):
            root=App()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as folder:
            root.local_state = Path(folder) / 'choices.json'
            root._catalog_app('app:nba2026','NBA 2026','Aplicativo','Registro')
            root.catalog_items['app:nba2026']['install_location']='D:/Jogos/NBA2026'
            root.apps_tree.selection_set('app:nba2026')
            with patch('app.messagebox.showwarning'):
                root.mark_catalog('app','keep')
            root.navigate(root.preservation)
            tree = next(t for t in descendants(root.preservation)
                        if isinstance(t,ttk.Treeview) and t['columns']==('type','drive','data'))
            rows=tree.get_children()
            self.assertTrue(any('NBA 2026' in tree.item(row,'text') for row in rows))
            selected = next(row for row in rows if 'NBA 2026' in tree.item(row,'text'))
            self.assertEqual(tree.set(selected,'drive'),'D:')
            self.assertIn('REVISÃO', tree.set(selected,'data'))
            self.assertEqual(root.catalog_choices['app:nba2026'],'keep')


if __name__ == '__main__': unittest.main()
