"""Tk integration regression for the current non-destructive backup review controls."""
import tkinter as tk
from tkinter import ttk
from unittest import TestCase
from unittest.mock import patch
from app import App
from tk_helpers import track_tk_root


def widgets(parent):
    for w in parent.winfo_children():
        yield w
        yield from widgets(w)


class SelectiveBackupScreen066(TestCase):
    def setUp(self):
        with patch.object(App, 'refresh_catalog', lambda self: None):
            self.app = App()
        track_tk_root(self, self.app)
        self.path = r'C:\Users\R\Saved Games\God of War Ragnarök'
        self.app.choices = {self.path: 'keep'}
        self.app.catalog_items = {'g': {'name': 'God of War Ragnarök', 'kind': 'game',
                                       'install_location': r'D:\Games\GOW'}}
        self.app.catalog_choices = {'g': 'keep'}
        self.app.approved_catalog_paths = {'g': [self.path]}
        self.app.update_preservation_preview()

    def test_current_review_has_safe_controls_and_no_legacy_dialog(self):
        self.app.navigate(self.app.review)
        self.app.update_idletasks()
        self.assertEqual(self.app.tabs.select(), str(self.app.review))
        buttons = [w for w in widgets(self.app.review) if isinstance(w, ttk.Button)]
        labels = [w.cget('text') for w in buttons]
        self.assertTrue(any('Recalcular plano e espaço' in s for s in labels))
        self.assertTrue(any('Iniciar backup (confirmação dupla)' in s for s in labels))
        self.assertTrue(any('Retomar backup interrompido' in s for s in labels))
        self.assertTrue(any('Histórico / Testar restauração' in s for s in labels))
        self.assertFalse(any('Formatar' in s or 'Apagar' in s for s in labels))
        self.assertEqual(str(self.app.backup_btn.cget('state')), 'disabled')
        self.assertFalse(any(isinstance(w, tk.Toplevel) and 'v0.6.6' in w.title()
                             for w in self.app.winfo_children()))
