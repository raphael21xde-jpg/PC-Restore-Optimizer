import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from deep_discovery_ui import show_deep_discovery


def record(path):
    return dict(app='osu!', app_id='osu', path=path, kind='Músicas e beatmaps',
                evidence='Teste', confidence='candidato', edition='stable')


class DriveDiscoveryGUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.root.choices = {}
        self.root.dest = tk.StringVar(value='G:\\Backup')
        self.root.catalog_items = {}
        self.root.deep_scan_report = dict(
            schema='pcro-discovery-v1', status='concluida_com_lacunas',
            roots=['C:\\', 'D:\\'], records=[record('C:/osu/Songs'), record('D:/osu/Songs')],
            volume_stats={'C:': {'directories': 248000, 'files': 500000},
                          'D:': {'directories': 20000, 'files': 90000}},
            errors=[], skipped=[], apps=[])

    def test_per_drive_tabs_only_show_own_paths(self):
        with patch('deep_discovery_ui.local_drives', return_value=['C:\\', 'D:\\']):
            show_deep_discovery(self.root)
        frame = next(w for w in self.root.winfo_children()[0].winfo_children() if isinstance(w, ttk.Frame))
        tabs = next(w for w in frame.winfo_children()
                    if isinstance(w, ttk.Notebook))
        tree = next(w for w in frame.winfo_children()
                    if isinstance(w, ttk.Frame) and any(isinstance(c, ttk.Treeview) for c in w.winfo_children()))
        tree = next(w for w in tree.winfo_children() if isinstance(w, ttk.Treeview))
        tabs.select(0)
        self.root.update()
        categories = tree.get_children()
        self.assertTrue(any(tree.item(i, 'text') == 'Jogos' for i in categories))
        osu = next(i for c in categories for i in tree.get_children(c) if tree.item(i, 'text').startswith('osu!'))
        tree.focus(osu)
        tree.item(osu, open=True)
        tree.event_generate('<<TreeviewOpen>>')
        self.root.update()
        self.assertTrue(any('C:/osu/Songs' in str(tree.item(i, 'values')) for i in tree.get_children(osu)))
        tabs.select(1)
        self.root.update()
        categories = tree.get_children()
        osu = next(i for c in categories for i in tree.get_children(c) if tree.item(i, 'text').startswith('osu!'))
        tree.focus(osu)
        tree.item(osu, open=True)
        tree.event_generate('<<TreeviewOpen>>')
        self.root.update()
        self.assertTrue(any('D:/osu/Songs' in str(tree.item(i, 'values')) for i in tree.get_children(osu)))
        self.assertFalse(any('C:/osu/Songs' in str(tree.item(i, 'values')) for i in tree.get_children(osu)))
        self.assertLess(len(tree.get_children()), 8)


if __name__ == '__main__':
    unittest.main()
