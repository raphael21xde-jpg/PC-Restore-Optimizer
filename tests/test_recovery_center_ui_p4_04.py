"""P4-04 (Fatia 5): testes de `recovery_center_ui.py` com `ui_scale`."""
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
SOURCE = (ROOT / 'recovery_center_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class RecoveryCenterUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('padding=14', SOURCE)
        self.assertNotIn('padx=(7, 0)', SOURCE)

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
            'TAMANHO_CORPO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_bar_packed_before_grid_and_texts_preserved(self):
        tools_pos = SOURCE.index("tools.pack(side='bottom', fill='x'")
        grid_pos = SOURCE.index("grid.pack(fill='both', expand=True)")
        self.assertLess(tools_pos, grid_pos)

        self.assertIn('Central de recuperação', SOURCE)
        self.assertIn('Clique em "Escolher pasta" para procurar os seus backups.', SOURCE)
        for label in (
            'Escolher pasta',
            'Conferir integridade',
            'Restaurar…',
            'Restaurar só os conferidos…',
            'Fechar',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class RecoveryCenterUiTkTests(unittest.TestCase):
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

    def test_geometry_title_font_and_empty_or_long_rows(self):
        root = self._new_root()
        import recovery_center_ui as rcu

        with tempfile.TemporaryDirectory() as tmp:
            long_name = 'Backup_' + ('Acentos_e_Símbolos_' * 8) + 'fim'
            long_reason = 'Motivo_' + ('Descrição_Muito_Longa_Sem_Espaços_' * 6)
            fake_rows = [
                {
                    'name': long_name,
                    'folder': 'backup-1',
                    'date': '2026-11-17',
                    'status_text': 'Concluído',
                    'files': '12',
                    'size_text': '1,5 MiB',
                    'restorable': True,
                    'partial_ok': False,
                    'reason': long_reason,
                    'manifest': Path(tmp) / 'manifest.json',
                },
            ]
            dlg = rcu.show_recovery_center(
                root,
                scanner=lambda _chosen, _cancelled: {'rows': fake_rows, 'warnings': []},
            )
            dlg.update_idletasks()

            self.assertEqual(dlg.minsize(), (760, 440))

            title_labels = [
                w for w in _walk_widgets(dlg)
                if isinstance(w, ttk.Label) and str(w.cget('text')) == rcu.TITLE
            ]
            self.assertEqual(len(title_labels), 1)
            font_str = str(title_labels[0].cget('font'))
            self.assertIn(ui_scale.FONTE_UI, font_str)
            self.assertIn(str(ui_scale.TAMANHO_TITULO_MODAL), font_str)

            buttons = {
                str(w.cget('text')): w
                for w in _walk_widgets(dlg)
                if isinstance(w, ttk.Button)
            }
            for label in (
                'Escolher pasta',
                'Conferir integridade',
                'Restaurar…',
                'Restaurar só os conferidos…',
                'Fechar',
            ):
                self.assertIn(label, buttons)

            dlg.center_search(Path(tmp))
            deadline_iters = 0
            while dlg.center_state['busy'] and deadline_iters < 100:
                dlg.update()
                root.after(20)
                deadline_iters += 1
            dlg.update_idletasks()

            self.assertEqual(len(dlg.center_tree.get_children('')), 1)
            self.assertIn('1 backup(s) encontrado(s)', dlg.center_status.get())
