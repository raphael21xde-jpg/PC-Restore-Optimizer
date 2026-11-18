"""P4-04 (Fatia 13): testes de `restore_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import tempfile
import time
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
SOURCE = (ROOT / 'restore_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class RestoreUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        for old_literal in (
            'padding=14',
            'padx=(0, 7)',
            'padx=(7, 0)',
            'padx=(9, 0)',
            'padx=12',
            'pady=(0, 7)',
            'pady=(5, 4)',
            'pady=(6, 2)',
            'pady=(5, 2)',
            'pady=(5, 6)',
            'pady=4',
            'padx=(0, 8)',
            'padx=10, pady=10',
            'pady=(0, 10)',
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
            'COR_PERIGO',
            'COR_SELECAO',
            'COR_TEXTO',
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_M',
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
        grid_idx = SOURCE.index("grid.pack(fill='both', expand=True")
        for bottom_call in (
            "actions.pack(side='bottom', fill='x')",
            "tools.pack(side='bottom', fill='x'",
            "selected_label.pack(side='bottom', fill='x'",
            "hint_label.pack(side='bottom', fill='x')",
        ):
            self.assertLess(SOURCE.index(bottom_call), grid_idx)

        for label in (
            'Restauração organizada — sem substituir arquivos originais',
            'Marcar grupo / item',
            'Desmarcar grupo / item',
            'Limpar seleção',
            'Programas do backup',
            'Launchers de jogos',
            'Restaurar arquivos marcados para pasta nova',
            'Retomar restauração interrompida',
            'Colocar no lugar original',
            'Retomar colocação interrompida',
            'Cancelar operação',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class RestoreUiTkTests(unittest.TestCase):
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

    def _wait_idle(self, root, timeout=4.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            if not getattr(root, 'busy', False):
                return
            time.sleep(0.01)
        self.fail('Janela de restauração não terminou o carregamento no tempo esperado.')

    def test_dialog_minsize_elevated_color_and_long_entry(self):
        root = self._new_root()
        root.busy = False
        import restore_ui

        long_key = 'documents/PastaMuitoLonga_ComAcentos_ção_é_' + ('X' * 150) + '.txt'
        entries = {
            long_key: {'bytes': 1234, 'sha256': '0' * 64, 'source': r'C:\Exemplo\arq.txt'},
        }
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / 'manifest.json'
            manifest.write_text(json.dumps({'files': entries}), encoding='utf-8')
            with patch('restore_ui.verified_entries', return_value=entries):
                restore_ui.show_restore(root, manifest, elevation_probe=lambda: True)
                dlg = root.restore_dialog
                self.addCleanup(lambda: dlg.destroy() if dlg.winfo_exists() else None)
                self._wait_idle(root)
                dlg.update_idletasks()

                self.assertEqual(dlg.minsize(), (800, 500))

                elev_labels = [
                    w for w in _walk_widgets(dlg)
                    if isinstance(w, ttk.Label) and str(w.cget('foreground')).upper() == ui_scale.COR_PERIGO
                ]
                self.assertEqual(len(elev_labels), 1)

                buttons = {
                    str(w.cget('text'))
                    for w in _walk_widgets(dlg)
                    if isinstance(w, ttk.Button)
                }
                for label in (
                    'Marcar grupo / item',
                    'Desmarcar grupo / item',
                    'Limpar seleção',
                    'Programas do backup',
                    'Launchers de jogos',
                    'Restaurar arquivos marcados para pasta nova',
                    'Retomar restauração interrompida',
                    'Colocar no lugar original',
                    'Retomar colocação interrompida',
                    'Cancelar operação',
                ):
                    self.assertIn(label, buttons)
