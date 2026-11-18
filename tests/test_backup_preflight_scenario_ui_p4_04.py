"""P4-04 (Fatia 9): testes de `backup_preflight_scenario_ui.py` com `ui_scale`."""
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
SOURCE = (ROOT / 'backup_preflight_scenario_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class BackupPreflightScenarioUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn("'Consolas'", SOURCE)
        self.assertNotIn('padding=14', SOURCE)
        self.assertNotIn('padding=5', SOURCE)
        self.assertNotIn('padx=(5, 20)', SOURCE)
        self.assertNotIn('padx=(7, 25)', SOURCE)
        self.assertNotIn('padx=(7, 9)', SOURCE)
        self.assertNotIn('padx=(10, 0)', SOURCE)

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
            'ESPACO_G',
            'ESPACO_M',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_MONO',
            'FONTE_UI',
            'PADDING_ABA_NOTEBOOK',
            'PADDING_CAIXA_TEXTO',
            'PADDING_DIALOGO',
            'TAMANHO_CORPO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_bar_packed_before_section_and_texts_preserved(self):
        final_pos = SOURCE.index("final.pack(side='bottom', fill='x'")
        section_pos = SOURCE.index("section.pack(fill='both', expand=True)")
        self.assertLess(final_pos, section_pos)

        self.assertIn('Simular um plano de backup sem copiar arquivos', SOURCE)
        self.assertIn('1. Quais unidades contêm dados de origem?', SOURCE)
        self.assertIn('Resultado da simulação', SOURCE)
        for label in ('Simular — somente leitura', 'Copiar relatório', 'Fechar'):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class BackupPreflightScenarioUiTkTests(unittest.TestCase):
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

    def test_dark_theme_geometry_and_simulation_controls(self):
        root = self._new_root()
        import backup_preflight_scenario_ui as mod

        root.diagnostic_data = {
            'disks': {
                'volumes': [
                    {'DriveLetter': 'C:'},
                    {'DriveLetter': 'D:'},
                    {'DriveLetter': 'E:'},
                ],
            },
        }
        win = mod.show_backup_preflight_scenario(root)
        win.update_idletasks()

        self.assertEqual(win.minsize(), (730, 560))

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
        for label in ('Simular — somente leitura', 'Copiar relatório', 'Fechar'):
            self.assertIn(label, buttons)

    def test_missing_diagnostic_warns_without_opening_window(self):
        root = self._new_root()
        import backup_preflight_scenario_ui as mod

        root.diagnostic_data = {}
        with patch.object(mod.messagebox, 'showwarning') as warn:
            win = mod.show_backup_preflight_scenario(root)
        self.assertIsNone(win)
        warn.assert_called_once()
