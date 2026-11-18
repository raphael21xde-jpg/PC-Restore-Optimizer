"""P4-04 (Fatia 3): testes de `multi_source_offline_reopen_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
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
SOURCE = (ROOT / 'multi_source_offline_reopen_ui.py').read_text(encoding='utf-8')


class MultiSourceOfflineReopenStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_removes_off_scale_spacing(self):
        for old_literal in (
            'padding=15',
            '(7, 3)',
            '(7, 8)',
            '(0, 9)',
            '(0, 6)',
            '(12, 10)',
            'padx=10',
            "'Segoe UI'",
        ):
            self.assertNotIn(old_literal, SOURCE)

        tree = ast.parse(SOURCE)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported.update(alias.name for alias in node.names)

        expected = {
            'ESPACO_DENTRO_GRUPO',
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_M',
            'ESPACO_P',
            'FONTE_UI',
            'PADDING_DIALOGO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported))

    def test_bottom_buttons_packed_before_treeview_and_texts_preserved(self):
        buttons_pos = SOURCE.index("buttons.pack(side='bottom', fill='x')")
        tree_pos = SOURCE.index('listview.pack(')
        self.assertLess(buttons_pos, tree_pos)

        for label in (
            'Reabrir cópias após reinstalação — demonstração',
            'Pasta de backup de teste:',
            'Adicionar',
            'Escolher pasta…',
            'Remover pasta',
            'Reabrir backups de teste',
            'Cancelar / Fechar',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class MultiSourceOfflineReopenTkTests(unittest.TestCase):
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

    def test_window_geometry_scale_and_long_path_break_ui(self):
        root = self._new_root()
        import multi_source_offline_reopen_ui as mod

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        sandbox = Path(tmp.name)
        restore_dir = sandbox / 'restaurar'
        restore_dir.mkdir()
        long_backup = sandbox / ('copia_segura_com_acentos_e_nome_muito_longo_' * 3 + 'fim')
        long_backup.mkdir()

        dlg = mod.show_fixture_offline_reopen(
            root,
            test_root=str(sandbox),
            restore_parent=str(restore_dir),
            initial_backup_roots=[str(long_backup)],
        )
        self.addCleanup(lambda: dlg.winfo_exists() and dlg.destroy())
        dlg.update_idletasks()

        self.assertEqual(dlg.minsize(), (660, 420))

        frames = [w for w in _walk_widgets(dlg) if isinstance(w, ttk.Frame)]
        root_frame = frames[0]
        self.assertEqual(str(root_frame.cget('padding')[0]), str(ui_scale.PADDING_DIALOGO))

        trees = [w for w in _walk_widgets(dlg) if isinstance(w, ttk.Treeview)]
        self.assertEqual(len(trees), 1)
        items = trees[0].get_children('')
        self.assertEqual(len(items), 1)
        self.assertIn(long_backup.name, trees[0].item(items[0], 'text'))

        buttons = {
            str(w.cget('text')): w
            for w in _walk_widgets(dlg)
            if isinstance(w, ttk.Button)
        }
        for label in (
            'Adicionar',
            'Escolher pasta…',
            'Remover pasta',
            'Reabrir backups de teste',
            'Cancelar / Fechar',
        ):
            self.assertIn(label, buttons)

        buttons['Cancelar / Fechar'].invoke()
        dlg.update_idletasks()
        self.assertFalse(dlg.winfo_exists())
