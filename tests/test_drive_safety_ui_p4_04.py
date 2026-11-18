"""P4-04 (Fatia 11): testes de `drive_safety_ui.py` com `ui_scale`."""
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
SOURCE = (ROOT / 'drive_safety_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class DriveSafetyUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        for old_literal in (
            'padding=16',
            'padx=(10, 0)',
            'pady=(6, 8)',
            'pady=(0, 9)',
            'pady=(9, 7)',
            'pady=(2, 8)',
            'pady=(0, 10)',
            'pady=(12, 0)',
            'pady=4',
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
            'ESPACO_MINIMO',
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
        self.assertLess(
            SOURCE.index("controls.pack(side='bottom', fill='x'"),
            SOURCE.index("items.pack(fill='both', expand=True"),
        )
        self.assertLess(
            SOURCE.index("controls.pack(side='bottom', fill='x'"),
            SOURCE.index("details.pack(fill='both', expand=True)"),
        )

        for label in (
            'Conferência de discos lógicos e destinos',
            'Origens a preservar:',
            'Destinos candidatos:',
            'Tamanho estimado do backup (GiB, opcional):',
            'Conferir discos (SOMENTE LEITURA)',
            'Usar tamanho da prévia',
            'Copiar resumo seguro',
            'Fechar',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class DriveSafetyUiTkTests(unittest.TestCase):
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

    def test_dialog_theme_minsize_and_bad_input_layout(self):
        root = self._new_root()
        from drive_safety_ui import show_drive_safety_dialog

        dialog = show_drive_safety_dialog(root, available_letters=('C', 'D', 'G'))
        self.addCleanup(lambda: dialog.destroy() if dialog.winfo_exists() else None)
        dialog.update_idletasks()

        self.assertEqual(dialog.minsize(), (720, 480))

        ttk_entries = [w for w in _walk_widgets(dialog) if isinstance(w, ttk.Entry)]
        tk_entries = [w for w in _walk_widgets(dialog) if type(w) is tk.Entry]
        texts = [w for w in _walk_widgets(dialog) if isinstance(w, tk.Text)]
        self.assertEqual(len(ttk_entries), 2)
        self.assertEqual(len(tk_entries), 1)
        self.assertEqual(len(texts), 1)

        size_input = tk_entries[0]
        self.assertEqual(size_input.cget('bg'), ui_scale.COR_PAINEL)
        self.assertEqual(size_input.cget('fg'), ui_scale.COR_TEXTO)
        self.assertEqual(size_input.cget('selectbackground'), ui_scale.COR_SELECAO)
        self.assertEqual(size_input.cget('highlightbackground'), ui_scale.COR_BORDA)

        details = texts[0]
        self.assertEqual(details.cget('bg'), ui_scale.COR_PAINEL)
        self.assertEqual(details.cget('fg'), ui_scale.COR_TEXTO)
        self.assertEqual(details.cget('selectbackground'), ui_scale.COR_SELECAO)
        self.assertEqual(details.cget('highlightbackground'), ui_scale.COR_BORDA)
        self.assertEqual(int(details.cget('padx')), ui_scale.PADDING_CAIXA_TEXTO[0])
        self.assertEqual(int(details.cget('pady')), ui_scale.PADDING_CAIXA_TEXTO[1])

        # Dados ruins: texto longo com acentos sem espaços nos campos.
        long_text = 'C:,D:,UnidadeMuitoLonga_ComAcentos_ção_é_' + ('X' * 160)
        ttk_entries[0].insert(0, long_text)
        size_input.insert(0, '1234567890,5')
        dialog.update_idletasks()

        buttons = {
            str(w.cget('text'))
            for w in _walk_widgets(dialog)
            if isinstance(w, ttk.Button)
        }
        for label in (
            'Conferir discos (SOMENTE LEITURA)',
            'Usar tamanho da prévia',
            'Copiar resumo seguro',
            'Fechar',
        ):
            self.assertIn(label, buttons)
