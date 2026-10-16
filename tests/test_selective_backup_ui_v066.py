"""Live Tk integration of the v0.6.6 non-destructive backup entry point."""
import tkinter as tk
from tkinter import ttk
from unittest import TestCase
from unittest.mock import patch
from app import App


def widgets(parent):
    for w in parent.winfo_children():
        yield w
        yield from widgets(w)


class SelectiveBackupScreen066(TestCase):
    def setUp(self):
        with patch.object(App, 'refresh_catalog', lambda self:None):
            self.app=App()
        self.addCleanup(self.app.destroy)
        self.path = r'C:\Users\R\Saved Games\God of War Ragnarök'
        self.app.choices={self.path:'keep'}
        self.app.catalog_items={'g': {'name':'God of War Ragnarök', 'kind':'game',
                                    'install_location':r'D:\Games\GOW'}}
        self.app.catalog_choices={'g':'keep'}
        self.app.approved_catalog_paths={'g':[self.path]}
        self.app.update_preservation_preview()

    def test_live_entry_and_safe_controls(self):
        button=next(w for w in widgets(self.app.preservation) if isinstance(w,ttk.Button)
                    and w.cget('text').startswith('Backup seletivo e TESTE'))
        button.invoke()
        self.app.update()
        windows=[x for x in self.app.winfo_children() if isinstance(x,tk.Toplevel)
                 and 'v0.6.6' in x.title()]
        self.assertEqual(len(windows),1)
        window=windows[0]
        try:
            labels=[w.cget('text') for w in widgets(window) if isinstance(w,ttk.Button)]
            self.assertTrue(any('Analisar arquivos do C:' in s for s in labels))
            self.assertTrue(any('SHA-256' in s for s in labels))
            self.assertTrue(any('Recuperação de TESTE' in s for s in labels))
            self.assertFalse(any('Formatar' in s or 'Apagar' in s for s in labels))
        finally:
            window.destroy()
