"""P4-04 (Fatia 1): testes da padronização visual de `launcher_guide_ui.py`."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import time
import unittest

import game_launchers as gl
import ui_scale

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tk_helpers import track_tk_root

try:
    import tkinter as tk
    from tkinter import ttk
    from launcher_guide_ui import show_launchers
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ttk = show_launchers = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


class LauncherGuideStaticScaleTests(unittest.TestCase):
    """Testes que rodam mesmo sem `tkinter` instalado."""

    def test_imports_ui_scale_tokens_and_has_no_off_scale_padding(self):
        src = (ROOT / 'launcher_guide_ui.py').read_text(encoding='utf-8')
        tree = ast.parse(src, filename='launcher_guide_ui.py')
        imported_from_ui_scale = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                for alias in node.names:
                    imported_from_ui_scale.add(alias.name)
        for expected in (
            'PADDING_DIALOGO',
            'ESPACO_M',
            'ESPACO_P',
            'ESPACO_MINIMO',
            'COR_PAINEL',
            'COR_TEXTO',
            'COR_BORDA',
            'FONTE_UI',
            'TAMANHO_CORPO',
            'TAMANHO_SUBTITULO',
            'safe_window_geometry',
        ):
            self.assertIn(expected, imported_from_ui_scale)

        # Nenhum valor antigo fora da escala (14, 6, 7, 2) usado em padding/padx/pady
        for old_literal in ('padding=14', 'pady=(4, 6)', 'pady=(0, 2)', 'pady=(0, 6)',
                            'pady=(8, 6)', 'padx=(7, 0)'):
            self.assertNotIn(old_literal, src)

    def test_safe_geometry_for_launcher_guide_at_125_and_150_dpi(self):
        # Em 150% num monitor 1920x1080 (1280x720 lógicos), 960x620 cabe com margem 80
        self.assertEqual(
            ui_scale.safe_window_geometry(960, 620, 1280, 720, min_w=640, min_h=440),
            '960x620',
        )
        # Em tela menor (ex.: 1024x600), reduz a altura sem cortar abaixo de min_h=440
        self.assertEqual(
            ui_scale.safe_window_geometry(960, 620, 1024, 600, min_w=640, min_h=440),
            '944x520',
        )


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class LauncherGuideVisualScaleWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)

    def widgets(self, cls, widget):
        if isinstance(widget, cls):
            yield widget
        for child in widget.winfo_children():
            yield from self.widgets(cls, child)

    def wait(self, dlg):
        until = time.monotonic() + 5
        while dlg.launcher_state['busy'] and time.monotonic() < until:
            self.root.update()
            time.sleep(0.02)
        self.assertFalse(dlg.launcher_state['busy'])

    def test_guide_text_uses_dark_theme_and_scale_padding(self):
        dlg = show_launchers(
            self.root,
            roots=['X'],
            scanner=lambda roots, cancelled=None: {
                'libraries': [],
                'truncated': False,
                'warnings': [],
            },
        )
        self.wait(dlg)
        text = next(self.widgets(tk.Text, dlg))
        self.assertEqual(str(text.cget('bg')).upper(), ui_scale.COR_PAINEL)
        self.assertEqual(str(text.cget('fg')).upper(), ui_scale.COR_TEXTO)
        self.assertEqual(int(str(text.cget('padx'))), ui_scale.ESPACO_M)
        self.assertEqual(int(str(text.cget('pady'))), ui_scale.ESPACO_P)
        dlg.destroy()

    def test_break_ui_long_paths_and_many_games_keep_controls_intact(self):
        long_path = 'D:\\' + ('PastaMuitoLongaSemEspaco_' * 8) + 'SteamLibrary'
        many_games = [f'Jogo Com Nome Longo e Acentos ÁÉÍÓÚ #{i}' for i in range(60)]
        fake = {
            'libraries': [
                {
                    'launcher': gl.STEAM,
                    'path': long_path,
                    'root': 'D:\\',
                    'games': many_games,
                    'confidence': gl.PROBABLE,
                    'on_system_drive': False,
                },
            ],
            'truncated': False,
            'warnings': [],
        }
        dlg = show_launchers(self.root, roots=['D:\\'], scanner=lambda r, cancelled=None: fake)
        self.wait(dlg)
        tree = next(self.widgets(ttk.Treeview, dlg))
        rows = tree.get_children('')
        self.assertEqual(len(rows), 1)
        tree.selection_set(rows[0])
        self.root.update()
        text = next(self.widgets(tk.Text, dlg))
        content = text.get('1.0', 'end')
        self.assertIn(long_path, content)
        self.assertIn(many_games[0], content)
        buttons = {b.cget('text'): b for b in self.widgets(ttk.Button, dlg)}
        for name in ('Pesquisar de novo', 'Copiar caminho', 'Fechar'):
            self.assertIn(name, buttons)
        dlg.destroy()


if __name__ == '__main__':
    unittest.main()
