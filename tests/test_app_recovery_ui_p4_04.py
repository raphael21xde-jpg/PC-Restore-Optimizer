"""P4-04 (Fatia 12): testes de `app_recovery_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

import ui_scale
from tests.tk_helpers import track_tk_root

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover - servidor Linux sem tkinter
    tk = None
    ttk = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app_recovery_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class AppRecoveryUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        for old_literal in (
            'padding=12',
            'padx=3',
            'padx=4',
            'padx=6',
            'pady=4',
            'pady=5',
            'pady=6',
            'pady=7',
            'pady=8',
        ):
            self.assertNotIn(old_literal, SOURCE)

        tree = ast.parse(SOURCE)
        imported_from_ui_scale: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported_from_ui_scale.update(alias.name for alias in node.names)

        expected = {
            'COR_BORDA',
            'COR_PAINEL',
            'COR_SELECAO',
            'COR_TEXTO',
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_P',
            'FONTE_MONO',
            'FONTE_UI',
            'PADDING_CAIXA_TEXTO',
            'PADDING_DIALOGO',
            'TAMANHO_CORPO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_controls_packed_before_expandable_widgets_and_texts_preserved(self):
        output_idx = SOURCE.index("output.pack(fill='both', expand=True)")
        tree_idx = SOURCE.index("tree.pack(fill='x'")
        for bottom_call in (
            "status_label.pack(side='bottom'",
            "lower.pack(side='bottom'",
            "actions.pack(side='bottom'",
            "row.pack(side='bottom'",
            "searchrow.pack(side='bottom'",
        ):
            idx = SOURCE.index(bottom_call)
            self.assertLess(idx, tree_idx)
            self.assertLess(idx, output_idx)

        for label in (
            'Recuperar aplicativos, jogos e saves',
            'Usar escolhas atuais',
            'Abrir plano salvo antes da formatação',
            '1. Buscar programa no WinGet',
            '2. Conferir pacote escolhido',
            '3. Instalar pacote confirmado',
            '4. Verificar instalação',
            'Orientação do launcher / jogos',
            'Recuperar dados / saves deste item',
            'Ajuda para instalar WinGet',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class AppRecoveryUiTkTests(unittest.TestCase):
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

    def test_dialog_dark_output_minsize_and_long_item(self):
        root = self._new_root()
        long_name = 'AplicativoMuitoLongo_ComAcentos_ção_é_' + ('X' * 150)
        root.catalog_items = {
            'app-longo': {
                'kind': 'app',
                'name': long_name,
                'source': 'winget',
                'edition': 'Standard',
                'publisher': 'Editora Exemplo',
                'version': '1.2.3',
                'paths': [r'C:\Users\Exemplo\AppData\Roaming\LongApp'],
            },
        }
        root.catalog_choices = {'app-longo': 'keep'}

        from app_recovery_ui import show_app_recovery

        win = show_app_recovery(root)
        self.addCleanup(lambda: win.destroy() if win.winfo_exists() else None)
        win.update_idletasks()

        self.assertEqual(win.minsize(), (720, 520))

        texts = [w for w in _walk_widgets(win) if isinstance(w, tk.Text)]
        trees = [w for w in _walk_widgets(win) if isinstance(w, ttk.Treeview)]
        self.assertEqual(len(texts), 1)
        self.assertEqual(len(trees), 1)
        self.assertEqual(len(trees[0].get_children()), 1)

        output = texts[0]
        self.assertEqual(output.cget('bg'), ui_scale.COR_PAINEL)
        self.assertEqual(output.cget('fg'), ui_scale.COR_TEXTO)
        self.assertEqual(output.cget('selectbackground'), ui_scale.COR_SELECAO)
        self.assertEqual(output.cget('highlightbackground'), ui_scale.COR_BORDA)
        self.assertEqual(int(output.cget('padx')), ui_scale.PADDING_CAIXA_TEXTO[0])
        self.assertEqual(int(output.cget('pady')), ui_scale.PADDING_CAIXA_TEXTO[1])

        buttons = {
            str(w.cget('text'))
            for w in _walk_widgets(win)
            if isinstance(w, ttk.Button)
        }
        for label in (
            'Usar escolhas atuais',
            'Abrir plano salvo antes da formatação',
            '1. Buscar programa no WinGet',
            '2. Conferir pacote escolhido',
            '3. Instalar pacote confirmado',
            '4. Verificar instalação',
            'Orientação do launcher / jogos',
            'Recuperar dados / saves deste item',
            'Ajuda para instalar WinGet',
        ):
            self.assertIn(label, buttons)
