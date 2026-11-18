"""P4-04 (Fatia 7): testes de `multi_source_recovery_center_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import tempfile
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
SOURCE = (ROOT / 'multi_source_recovery_center_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class MultiSourceRecoveryCenterUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('padding=14', SOURCE)
        self.assertNotIn('padx=(14, 5)', SOURCE)
        self.assertNotIn('pady=(3, 10)', SOURCE)
        self.assertNotIn('padx=(0, 8)', SOURCE)

        tree = ast.parse(SOURCE)
        imported_from_ui_scale: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported_from_ui_scale.update(alias.name for alias in node.names)

        expected = {
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_M',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_UI',
            'PADDING_DIALOGO',
            'TAMANHO_CORPO',
            'TAMANHO_SUBTITULO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_bar_packed_before_files_view_and_texts_preserved(self):
        actions_pos = SOURCE.index("actions.pack(side='bottom', fill='x'")
        files_pos = SOURCE.index("files_view.pack(fill='both', expand=True")
        self.assertLess(actions_pos, files_pos)

        self.assertIn('Cópias disponíveis', SOURCE)
        self.assertIn('Arquivos selecionáveis', SOURCE)
        self.assertIn('Resultado da última recuperação verificada', SOURCE)
        for label in (
            'Verificar cópias (SHA-256)',
            'Marcar/desmarcar arquivo',
            'Restaurar selecionados (TESTE)',
            'Cancelar / Fechar',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class MultiSourceRecoveryCenterUiTkTests(unittest.TestCase):
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

    def test_geometry_tables_and_bad_data(self):
        root = self._new_root()
        import multi_source_recovery_center_ui as mod

        with tempfile.TemporaryDirectory() as tmp:
            restore_parent = Path(tmp) / 'restore'
            restore_parent.mkdir()
            long_path = 'D:\\Cópias\\' + ('Pasta_Muito_Longa_Com_Acentos_e_Símbolos_' * 4) + 'fim'
            dlg = mod.show_fixture_recovery_center(
                root,
                {},
                {'destinations': [{'path': long_path}]},
                test_root=tmp,
                restore_parent=restore_parent,
            )
            dlg.update_idletasks()

            self.assertEqual(dlg.minsize(), (750, 510))
            trees = [w for w in _walk_widgets(dlg) if isinstance(w, ttk.Treeview)]
            self.assertEqual(len(trees), 3)
            self.assertEqual(len(trees[0].get_children('')), 1)

            buttons = {
                str(w.cget('text')): w
                for w in _walk_widgets(dlg)
                if isinstance(w, ttk.Button)
            }
            for label in (
                'Verificar cópias (SHA-256)',
                'Marcar/desmarcar arquivo',
                'Restaurar selecionados (TESTE)',
                'Cancelar / Fechar',
            ):
                self.assertIn(label, buttons)

    def test_empty_destinations(self):
        root = self._new_root()
        import multi_source_recovery_center_ui as mod

        with tempfile.TemporaryDirectory() as tmp:
            restore_parent = Path(tmp) / 'restore'
            restore_parent.mkdir()
            dlg = mod.show_fixture_recovery_center(
                root,
                {},
                {'destinations': []},
                test_root=tmp,
                restore_parent=restore_parent,
            )
            dlg.update_idletasks()

            trees = [w for w in _walk_widgets(dlg) if isinstance(w, ttk.Treeview)]
            self.assertEqual(len(trees[0].get_children('')), 0)
