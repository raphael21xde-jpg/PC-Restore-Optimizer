"""P4-04 (Fatia 2): testes de `multi_backup_destinations_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import ui_scale
from tests.tk_helpers import track_tk_root

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover - servidor Linux sem tkinter
    tk = None
    ttk = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'multi_backup_destinations_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class MultiBackupDestinationsStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_inline_hex(self):
        self.assertNotIn('#C79229', SOURCE)
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('padding=14', SOURCE)

        tree = ast.parse(SOURCE)
        imported_from_ui_scale: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported_from_ui_scale.update(alias.name for alias in node.names)

        expected = {
            'COR_ALERTA',
            'COR_BORDA',
            'COR_PAINEL',
            'COR_SELECAO',
            'COR_TEXTO',
            'ESPACO_DENTRO_GRUPO',
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_UI',
            'PADDING_DIALOGO',
            'TAMANHO_CORPO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_button_bar_packed_before_listbox_and_texts_preserved(self):
        row_pos = SOURCE.index("row.pack(side='bottom', fill='x')")
        listbox_pos = SOURCE.index('listbox.pack(')
        self.assertLess(row_pos, listbox_pos)

        self.assertIn('Para onde copiar o backup?', SOURCE)
        self.assertIn('Selecione de 1 a 8 pastas existentes em discos diferentes de C:.', SOURCE)
        self.assertIn('O aplicativo NÃO conecta Google Drive/OneDrive por API nesta versão', SOURCE)
        self.assertIn('Adicionar pasta escolhida', SOURCE)
        self.assertIn('Remover selecionada', SOURCE)
        self.assertIn('Usar estes destinos', SOURCE)
        self.assertIn('Cancelar', SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class MultiBackupDestinationsTkTests(unittest.TestCase):
    """Testes com janela Tk real (ignorados quando não há display/tkinter)."""

    def _new_root(self):
        if tk is None:
            self.skipTest('tkinter indisponível neste ambiente')
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'display Tk indisponível: {exc}')
        root.withdraw()
        return track_tk_root(self, root)

    def test_dark_theme_geometry_and_bad_data_layout(self):
        root = self._new_root()
        import multi_backup_destinations_ui as mod

        long_path = 'D:\\Backups\\' + ('Pasta_Muito_Longa_Com_Acentos_e_Símbolos_' * 4) + 'fim'
        initial = [
            {'path': long_path, 'kind': 'local'},
            {'path': 'E:\\Nuvem\\Drive', 'kind': 'synced_folder'},
        ]
        saved = []
        dlg = mod.open_destination_picker(root, initial, saved.append)
        dlg.update_idletasks()

        self.assertEqual(dlg.minsize(), (650, 410))

        listboxes = [w for w in _walk_widgets(dlg) if isinstance(w, tk.Listbox)]
        self.assertEqual(len(listboxes), 1)
        lb = listboxes[0]
        self.assertEqual(lb.cget('bg'), ui_scale.COR_PAINEL)
        self.assertEqual(lb.cget('fg'), ui_scale.COR_TEXTO)
        self.assertEqual(lb.cget('selectbackground'), ui_scale.COR_SELECAO)
        self.assertEqual(lb.cget('highlightbackground'), ui_scale.COR_BORDA)
        self.assertEqual(lb.size(), 2)
        self.assertIn(long_path, lb.get(0))

        cloud_labels = [
            w for w in _walk_widgets(dlg)
            if isinstance(w, ttk.Label) and 'Nuvem:' in str(w.cget('text'))
        ]
        self.assertEqual(len(cloud_labels), 1)
        self.assertEqual(str(cloud_labels[0].cget('foreground')), ui_scale.COR_ALERTA)

        buttons = {
            str(w.cget('text')): w
            for w in _walk_widgets(dlg)
            if isinstance(w, ttk.Button)
        }
        for label in ('Adicionar pasta escolhida', 'Remover selecionada', 'Usar estes destinos', 'Cancelar'):
            self.assertIn(label, buttons)

        buttons['Usar estes destinos'].invoke()
        self.assertEqual(saved, [initial])

    def test_add_remove_and_empty_initial(self):
        root = self._new_root()
        import multi_backup_destinations_ui as mod

        saved = []
        dlg = mod.open_destination_picker(root, [], saved.append)
        dlg.update_idletasks()

        listboxes = [w for w in _walk_widgets(dlg) if isinstance(w, tk.Listbox)]
        lb = listboxes[0]
        self.assertEqual(lb.size(), 0)

        buttons = {
            str(w.cget('text')): w
            for w in _walk_widgets(dlg)
            if isinstance(w, ttk.Button)
        }

        with patch.object(mod.filedialog, 'askdirectory', return_value='D:\\NovoBackup'):
            buttons['Adicionar pasta escolhida'].invoke()
        self.assertEqual(lb.size(), 1)

        lb.selection_set(0)
        buttons['Remover selecionada'].invoke()
        self.assertEqual(lb.size(), 0)

        buttons['Cancelar'].invoke()
        self.assertEqual(saved, [])
