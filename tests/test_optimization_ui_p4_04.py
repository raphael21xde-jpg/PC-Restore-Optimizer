"""P4-04 (Fatia 19): testes de `optimization_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
import re
from tempfile import TemporaryDirectory
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
SOURCE = (ROOT / 'optimization_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class OptimizationUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_hardcoded_colors_or_fonts(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn("'Consolas'", SOURCE)

        tree = ast.parse(SOURCE)
        imported_from_ui_scale: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported_from_ui_scale.update(alias.name for alias in node.names)

        expected = {
            'ACCENT',
            'AMBER',
            'BG',
            'BORDER',
            'COR_GRADE_GRAFICO',
            'ESPACO_ENTRE_BLOCOS',
            'ESPACO_ENTRE_BOTOES',
            'FONTE_MONO',
            'FONTE_UI',
            'GREEN',
            'MUTED',
            'PADDING_CAIXA_TEXTO',
            'PADDING_PAINEL_COMPACTO',
            'PANEL',
            'TAMANHO_APOIO',
            'TAMANHO_CORPO',
            'TAMANHO_SUBTITULO',
            'TEXT',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_preserves_tabs_and_key_labels(self):
        for expected_text in (
            'OTIMIZAÇÃO CONSCIENTE',
            '1  Diagnóstico',
            '2  Temperaturas e sessões',
            '3  Stutters / quadros',
            '4  Energia reversível',
            '5  Benchmarks',
            '6  BIOS e drivers',
            'Analisar este PC',
            'Check-up de segurança',
            'Aplicar plano selecionado',
            'Desfazer tudo',
            'Aplicar ajustes seguros',
            'Ver estado atual',
        ):
            self.assertIn(expected_text, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class OptimizationUiTkTests(unittest.TestCase):
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

    def test_panel_builds_nine_tabs_with_dark_palette_and_ttk_buttons(self):
        root = self._new_root()
        import optimization_ui
        with TemporaryDirectory() as tmp:
            panel = optimization_ui.OptimizationPanel(root, tmp, state_dir=tmp)
            panel.pack(fill='both', expand=True)
            root.update_idletasks()

            self.assertEqual(panel.cget('bg'), ui_scale.BG)
            self.assertEqual(len(panel.tabs.tabs()), 9)
            tab_texts = [panel.tabs.tab(tab_id, 'text') for tab_id in panel.tabs.tabs()]
            self.assertEqual(tab_texts[0], '1  Diagnóstico')
            self.assertEqual(tab_texts[-1], optimization_ui.ADVANCED_TAB_LABEL)

            buttons = [w for w in _walk_widgets(panel) if isinstance(w, ttk.Button)]
            button_texts = {b.cget('text') for b in buttons}
            self.assertIn('Analisar este PC', button_texts)
            self.assertIn('Aplicar plano selecionado', button_texts)
            self.assertIn('Desfazer tudo', button_texts)
            self.assertIn('Aplicar ajustes seguros', button_texts)

            for btn in (
                panel.btn_scan,
                panel.btn_bios_steps,
                panel.btn_checkup,
                panel.btn_idle,
                panel.btn_apply,
                panel.btn_undo_all,
                panel.btn_tweaks_apply,
            ):
                self.assertEqual(type(btn).__module__, ttk.Button.__module__)
                self.assertEqual(type(btn).__name__, ttk.Button.__name__)

    def test_report_popups_keep_footer_buttons_visible_at_minsize(self):
        root = self._new_root()
        import optimization_ui
        with TemporaryDirectory() as tmp:
            panel = optimization_ui.OptimizationPanel(root, tmp, state_dir=tmp)
            panel.report = {'bios_guidance': {}}

            bios_win = panel.show_bios_steps()
            self.assertIsNotNone(bios_win)
            try:
                bios_win.update_idletasks()
                min_w, min_h = bios_win.minsize()
                self.assertGreaterEqual(min_w, 320)
                self.assertGreaterEqual(min_h, 240)
                bios_win.geometry(f'{min_w}x{min_h}')
                bios_win.update_idletasks()
                close_btns = [
                    w for w in _walk_widgets(bios_win)
                    if isinstance(w, ttk.Button) and w.cget('text') == 'Fechar'
                ]
                self.assertEqual(len(close_btns), 1)
                self.assertGreater(close_btns[0].winfo_height(), 0)
            finally:
                if bios_win.winfo_exists():
                    bios_win.destroy()

            checkup_result = {
                'startup': [],
                'tasks': [],
                'processes': [],
                'defender': None,
                'network': None,
            }
            checkup_win = panel.show_checkup(checkup_result)
            self.assertIsNotNone(checkup_win)
            try:
                checkup_win.update_idletasks()
                min_w, min_h = checkup_win.minsize()
                self.assertGreaterEqual(min_w, 320)
                self.assertGreaterEqual(min_h, 240)
                checkup_win.geometry(f'{min_w}x{min_h}')
                checkup_win.update_idletasks()
                btns = {
                    w.cget('text'): w
                    for w in _walk_widgets(checkup_win)
                    if isinstance(w, ttk.Button)
                }
                self.assertIn('Fechar', btns)
                self.assertIn(optimization_ui.CHECKUP_SAVE_FULL_BUTTON, btns)
                self.assertGreater(btns['Fechar'].winfo_height(), 0)
                self.assertGreater(btns[optimization_ui.CHECKUP_SAVE_FULL_BUTTON].winfo_height(), 0)
            finally:
                if checkup_win.winfo_exists():
                    checkup_win.destroy()


if __name__ == '__main__':
    unittest.main()
