"""Run on Windows normally; Linux can run this with xvfb-run -a."""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    import tkinter as tk
    from tkinter import ttk
    from restore_ui import show_restore
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ttk = show_restore = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


@unittest.skipIf(NO_DISPLAY, 'No Tk or graphical display')
class GroupedRestoreWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.busy = False
        self.root.geometry('1000x700')
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def find(self, cls, widget=None):
        widget=widget or self.root
        if isinstance(widget, cls):
            yield widget
        for child in widget.winfo_children():
            yield from self.find(cls,child)

    def wait_ready(self):
        until=time.monotonic()+5
        while self.root.busy and time.monotonic()<until:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.root.busy,'background manifest index never finished')

    def fixture(self):
        entries={}
        for i in range(550):
            key=f'C/Games/osu!/Songs/set{i//3}/note{i}.osu'
            entries[key]={'source':fr'C:\Games\osu!\Songs\set{i//3}\note{i}.osu', 'bytes':512, 'owners':[]}
        entries['C/Games/Other/save.dat']={
            'source':r'C:\Games\Other\save.dat','bytes':99,
            'owners':[{'name':'Other Game','category':'Save do jogo','root':r'C:\Games\Other'}]}
        return entries

    def test_large_index_lazy_filter_and_persistent_selection(self):
        with patch('restore_ui.verified_entries', return_value=self.fixture()):
            show_restore(self.root, 'unused.json')
            self.wait_ready()
        dlg=self.root.restore_dialog
        trees=[t for t in self.find(ttk.Treeview,dlg)]
        self.assertEqual(len(trees),1)
        tree=trees[0]
        self.assertEqual(len(tree.get_children('')),2)
        osu=next(i for i in tree.get_children('') if 'osu!' in tree.item(i,'text'))
        self.assertEqual(tree.set(osu,'mark'),'[ ]')
        tree.focus(osu)
        tree.selection_set(osu)
        mark_button=next(b for b in self.find(ttk.Button,dlg) if b.cget('text')=='Marcar grupo / item')
        mark_button.invoke()
        self.assertEqual(tree.set(osu,'mark'),'[x]')
        entry=next(t for t in self.find(ttk.Entry,dlg))
        entry.insert(0,'note34.osu')
        until=time.monotonic()+2
        while time.monotonic()<until:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(len(tree.get_children('')),1)
        osu=tree.get_children('')[0]
        self.assertEqual(tree.set(osu,'mark'),'[x]')
        self.assertEqual(tree.set(osu,'count'),'1/550')
        label_texts=[w.cget('text') for w in self.find(ttk.Label,dlg)]
        self.assertTrue(any('550 arquivo' in val for val in label_texts),label_texts)
        # Expand search results without populating 550 file rows at once.
        tree.focus(osu)
        tree.item(osu,open=True)
        tree.event_generate('<<TreeviewOpen>>')
        self.root.update()
        self.assertEqual(len(tree.get_children(osu)),1)
        dlg.destroy()

    def test_small_file_is_preselected(self):
        with patch('restore_ui.verified_entries',return_value=self.fixture()):
            show_restore(self.root,'unused.json',small=True)
            self.wait_ready()
        tree=next(self.find(ttk.Treeview,self.root.restore_dialog))
        self.assertEqual(len(tree.get_children('')),1)
        self.assertEqual(tree.set(tree.get_children('')[0],'mark'),'[x]')
        self.root.restore_dialog.destroy()

    def test_place_original_controls_smoke(self):
        # P2-01 fatia 2: botoes presentes, caixa das pastas do sistema desmarcada,
        # e como administrador nada e perguntado nem gravado.
        with patch('restore_ui.verified_entries',return_value=self.fixture()):
            show_restore(self.root,'unused.json',elevation_probe=lambda: True)
            self.wait_ready()
        dlg=self.root.restore_dialog
        texts={b.cget('text'):b for b in self.find(ttk.Button,dlg)}
        self.assertIn('Colocar no lugar original',texts)
        self.assertIn('Retomar colocação interrompida',texts)
        box=next(c for c in self.find(ttk.Checkbutton,dlg)
                 if 'Program Files/ProgramData' in c.cget('text'))
        self.assertFalse(self.root.getvar(box.cget('variable')) in (1,'1',True))
        with patch('restore_ui.filedialog.askdirectory') as ask, \
                patch('restore_ui.messagebox.showerror') as error:
            texts['Colocar no lugar original'].invoke()
            texts['Retomar colocação interrompida'].invoke()
        ask.assert_not_called()
        self.assertEqual(error.call_count,2)
        dlg.destroy()

if __name__=='__main__':unittest.main()
