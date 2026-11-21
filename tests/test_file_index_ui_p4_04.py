"""P4-04 (Fatia 14): testes de `file_index_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.tk_helpers import track_tk_root
from ui_scale import safe_window_size

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover - servidor Linux sem tkinter
    tk = None
    ttk = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'file_index_ui.py').read_text(encoding='utf-8')


class FileIndexUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertNotIn('"Segoe UI"', SOURCE)
        self.assertNotIn("'Segoe UI'", SOURCE)
        for old_literal in (
            'padding=10',
            'padding=(10, 2)',
            'wraplength=790',
            'wraplength=800',
            'wraplength=465',
            'padx=4',
            'padx=6',
            'padx=14',
            'padx=18',
            'padx=(0, 6)',
            'padx=(0, 8)',
            'pady=(3, 7)',
            'pady=(6, 3)',
            'pady=(12, 9)',
            'pady=10',
            'geometry("510x340")',
            'minsize(410, 260)',
        ):
            self.assertNotIn(old_literal, SOURCE)

        tree = ast.parse(SOURCE)
        imported_from_ui_scale: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported_from_ui_scale.update(alias.name for alias in node.names)

        expected = {
            'ESPACO_FINO',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_UI',
            'PADDING_DIALOGO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_window_size',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_controls_packed_before_expandable_widgets_and_texts_preserved(self):
        self.assertLess(
            SOURCE.index('controls.pack(side="bottom", fill="x")'),
            SOURCE.index('main.pack(fill="both", expand=True)'),
        )
        self.assertLess(
            SOURCE.index('actions_popup.pack(side="bottom", fill="x"'),
            SOURCE.index('ttk.Checkbutton(popup,'),
        )

        for label in (
            'Inventário detalhado — somente metadados',
            'CRIAR índice detalhado (somente leitura das fontes)',
            'ABRIR índice anterior',
            'Exportar escolhas JSON',
            'ESCOLHER unidades',
            'Parar varredura',
            'Pesquisar',
            'Marcar PRESERVAR (arquivo/pasta)',
            'NÃO COPIAR (não apaga)',
            'Revisar depois',
            'Anterior 100',
            'Próximos 100',
            'Confirmar unidades',
            'Cancelar',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _assert_widget_visible_in(testcase, widget, container, label):
    testcase.assertTrue(widget.winfo_ismapped(), f'{label}: nao mapeado')
    w_x1 = widget.winfo_rootx()
    w_y1 = widget.winfo_rooty()
    w_x2 = w_x1 + widget.winfo_width()
    w_y2 = w_y1 + widget.winfo_height()
    c_x1 = container.winfo_rootx()
    c_y1 = container.winfo_rooty()
    c_x2 = c_x1 + container.winfo_width()
    c_y2 = c_y1 + container.winfo_height()
    testcase.assertGreaterEqual(w_x1, c_x1, f'{label}: cortado a esquerda ({w_x1} < {c_x1})')
    testcase.assertGreaterEqual(w_y1, c_y1, f'{label}: cortado acima ({w_y1} < {c_y1})')
    testcase.assertLessEqual(w_x2, c_x2, f'{label}: cortado a direita ({w_x2} > {c_x2})')
    testcase.assertLessEqual(w_y2, c_y2, f'{label}: cortado abaixo ({w_y2} > {c_y2})')


class FileIndexUiTkTests(unittest.TestCase):
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

    def test_window_and_roots_popup_with_bad_input_keep_controls_mapped(self):
        root = self._new_root()
        from file_index_ui import show_file_index

        win = show_file_index(root)
        try:
            win.update()
            self.assertEqual(tuple(int(x) for x in win.resizable()), (1, 1))
            expected_min = safe_window_size(
                620, 420, win.winfo_screenwidth(), win.winfo_screenheight()
            )
            min_w, min_h = win.minsize()
            self.assertEqual((min_w, min_h), expected_min)

            win.geometry(f'{min_w}x{min_h}')
            win.update()

            entries = [w for w in _walk_widgets(win) if isinstance(w, ttk.Entry)]
            self.assertEqual(len(entries), 1)
            search_entry = entries[0]
            search_entry.configure(state='normal')
            search_entry.insert(0, 'C:\\PastaMuitoLonga_SemEspacos_ção_é_' + ('X' * 160))
            win.update()

            buttons = {
                str(w.cget('text')): w
                for w in _walk_widgets(win)
                if isinstance(w, ttk.Button)
            }
            for label in (
                'CRIAR índice detalhado (somente leitura das fontes)',
                'ABRIR índice anterior',
                'Exportar escolhas JSON',
                'ESCOLHER unidades',
                'Parar varredura',
                'Pesquisar',
                'Marcar PRESERVAR (arquivo/pasta)',
                'NÃO COPIAR (não apaga)',
                'Revisar depois',
                'Anterior 100',
                'Próximos 100',
            ):
                self.assertIn(label, buttons)
                _assert_widget_visible_in(self, buttons[label], win, label)

            with tempfile.TemporaryDirectory(prefix='PCRO-UI-F14-') as tmp:
                long_root = Path(tmp) / ('Unidade_Muito_Longa_ção_é_' + ('Y' * 80))
                long_root.mkdir()
                with patch('file_index_ui.discover_local_roots', return_value=[long_root]):
                    buttons['ESCOLHER unidades'].invoke()
                    win.update()
                    popups = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
                    self.assertEqual(len(popups), 1)
                    popup = popups[0]
                    pop_expected_min = safe_window_size(
                        410, 260, popup.winfo_screenwidth(), popup.winfo_screenheight()
                    )
                    pop_min_w, pop_min_h = popup.minsize()
                    self.assertEqual((pop_min_w, pop_min_h), pop_expected_min)
                    popup.geometry(f'{pop_min_w}x{pop_min_h}')
                    popup.update()
                    pop_buttons = {
                        str(w.cget('text')): w
                        for w in _walk_widgets(popup)
                        if isinstance(w, ttk.Button)
                    }
                    _assert_widget_visible_in(
                        self, pop_buttons['Confirmar unidades'], popup, 'Confirmar unidades'
                    )
                    _assert_widget_visible_in(
                        self, pop_buttons['Cancelar'], popup, 'Cancelar'
                    )
                    popup_labels = [
                        w for w in popup.winfo_children() if isinstance(w, ttk.Label)
                    ]
                    self.assertEqual(len(popup_labels), 1)
                    self.assertGreater(int(popup_labels[0].cget('wraplength')), 320)
                    popup.destroy()
        finally:
            if win.winfo_exists():
                close_cmd = win.protocol('WM_DELETE_WINDOW')
                win.tk.call(close_cmd)

    def test_roots_popup_at_minimum_size_with_many_roots_keeps_actions_visible(self):
        root = self._new_root()
        from file_index_ui import show_file_index

        win = show_file_index(root)
        try:
            win.update()
            buttons = {
                str(w.cget('text')): w
                for w in _walk_widgets(win)
                if isinstance(w, ttk.Button)
            }
            with tempfile.TemporaryDirectory(prefix='PCRO-UI-F14-MANY-') as tmp:
                fake_roots = []
                for idx in range(10):
                    p = Path(tmp) / f'Unidade_{idx:02d}_Dados'
                    p.mkdir()
                    fake_roots.append(p)
                with patch('file_index_ui.discover_local_roots', return_value=fake_roots):
                    buttons['ESCOLHER unidades'].invoke()
                    win.update()
                    popups = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
                    self.assertEqual(len(popups), 1)
                    popup = popups[0]
                    pop_min_w, pop_min_h = popup.minsize()
                    popup.geometry(f'{pop_min_w}x{pop_min_h}')
                    popup.update()
                    pop_buttons = {
                        str(w.cget('text')): w
                        for w in _walk_widgets(popup)
                        if isinstance(w, ttk.Button)
                    }
                    _assert_widget_visible_in(
                        self, pop_buttons['Confirmar unidades'], popup, 'Confirmar unidades (10 roots)'
                    )
                    _assert_widget_visible_in(
                        self, pop_buttons['Cancelar'], popup, 'Cancelar (10 roots)'
                    )
                    popup.destroy()
        finally:
            if win.winfo_exists():
                close_cmd = win.protocol('WM_DELETE_WINDOW')
                win.tk.call(close_cmd)
