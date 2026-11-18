"""P4-04 (Fatia 6): testes de `browser_recovery_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
import re
from types import SimpleNamespace
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
SOURCE = (ROOT / 'browser_recovery_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class BrowserRecoveryUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('padding=16', SOURCE)
        self.assertNotIn('padx=(0, 8)', SOURCE)

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
            'ESPACO_M',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_UI',
            'PADDING_CAIXA_TEXTO',
            'PADDING_DIALOGO',
            'TAMANHO_CORPO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_controls_packed_before_details_and_texts_preserved(self):
        actions_pos = SOURCE.index("actions.pack(side='bottom', fill='x')")
        details_pos = SOURCE.index("details.pack(fill='both', expand=True, pady=ESPACO_P)")
        self.assertLess(actions_pos, details_pos)

        self.assertIn('Restaurar navegador', SOURCE)
        self.assertIn('1. Perfil de destino (abra o navegador uma vez para ele aparecer):', SOURCE)
        self.assertIn('2. Origem dos dados:', SOURCE)
        self.assertIn('3. Escolha o que importar.', SOURCE)
        for label in (
            'Abrir cofre com senha',
            'Usar pasta já recuperada',
            'Preparar favoritos',
            'Orientar importação de senhas',
            'Ajuda oficial do navegador',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class BrowserRecoveryUiTkTests(unittest.TestCase):
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

    def test_dark_theme_minsize_and_bad_data_profiles(self):
        root = self._new_root()
        import browser_recovery_ui as mod

        long_profile = SimpleNamespace(
            browser='Opera GX',
            label='Perfil_' + ('Acentos_e_Símbolos_' * 6),
            path=Path('C:\\Users\\Demo\\AppData\\Roaming\\') / ('Pasta_Longa_' * 8),
        )
        with patch.object(mod, 'discover_profiles', return_value=[long_profile]):
            win = mod.show_recovery(root)
            win.update_idletasks()

        self.assertEqual(win.minsize(), (640, 480))

        texts = [w for w in _walk_widgets(win) if isinstance(w, tk.Text)]
        self.assertEqual(len(texts), 1)
        txt = texts[0]
        self.assertEqual(txt.cget('bg'), ui_scale.COR_PAINEL)
        self.assertEqual(txt.cget('fg'), ui_scale.COR_TEXTO)
        self.assertEqual(txt.cget('selectbackground'), ui_scale.COR_SELECAO)
        self.assertEqual(txt.cget('highlightbackground'), ui_scale.COR_BORDA)
        self.assertEqual(int(txt.cget('padx')), ui_scale.PADDING_CAIXA_TEXTO[0])
        self.assertEqual(int(txt.cget('pady')), ui_scale.PADDING_CAIXA_TEXTO[1])

        buttons = {
            str(w.cget('text')): w
            for w in _walk_widgets(win)
            if isinstance(w, ttk.Button)
        }
        for label in (
            'Abrir cofre com senha',
            'Usar pasta já recuperada',
            'Preparar favoritos',
            'Orientar importação de senhas',
            'Ajuda oficial do navegador',
        ):
            self.assertIn(label, buttons)

    def test_empty_profiles_message(self):
        root = self._new_root()
        import browser_recovery_ui as mod

        with patch.object(mod, 'discover_profiles', return_value=[]):
            win = mod.show_recovery(root)
            win.update_idletasks()

        labels = [
            str(w.cget('text'))
            for w in _walk_widgets(win)
            if isinstance(w, ttk.Label)
        ]
        self.assertTrue(any('Nenhum perfil localizado.' in text for text in labels))
