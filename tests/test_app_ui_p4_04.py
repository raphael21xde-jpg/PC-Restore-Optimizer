"""P4-04 (Fatia 20): testes de aparência e escala visual em `app.py`."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from tests.tk_helpers import track_tk_root
from ui_scale import (
    ALTURA_MINIMA_TABELA_LINHAS,
    FONTE_UI,
    PANEL,
    TAMANHO_CORPO,
    TEXT,
    safe_window_geometry,
    safe_window_size,
)

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover - servidor Linux sem tkinter
    tk = None
    ttk = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app.py').read_text(encoding='utf-8')


class AppUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_duplicate_colors_or_fonts(self):
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('"Segoe UI"', SOURCE)
        self.assertNotIn("'Consolas'", SOURCE)
        self.assertNotIn('"Consolas"', SOURCE)
        for hex_color in (
            '#0C1220', '#192438', '#EFF4FF', '#9CAAC0', '#9C85FF',
            '#5DDEB1', '#10192A', '#2B3952', '#27334A', '#FFFFFF',
            '#F3BE67', '#B2A2FF', '#394C75', '#235781',
        ):
            self.assertNotIn(hex_color, SOURCE)
        self.assertNotIn('height=2)', SOURCE)

        tree = ast.parse(SOURCE)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported.update(alias.name for alias in node.names)

        expected = {
            'ACCENT',
            'ALTURA_LINHA_TABELA',
            'ALTURA_MINIMA_TABELA_LINHAS',
            'AMBER',
            'BG',
            'BORDER',
            'COR_DESTAQUE_ATIVO',
            'COR_SELECAO',
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_FINO',
            'ESPACO_G',
            'ESPACO_GG',
            'ESPACO_M',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_MONO',
            'FONTE_SIMBOLO',
            'FONTE_UI',
            'GREEN',
            'HOVER',
            'MUTED',
            'PADDING_BOTAO',
            'PADDING_CABECALHO_TABELA',
            'PADDING_CAIXA_TEXTO',
            'PADDING_CAMPO_ENTRADA',
            'PADDING_DIALOGO',
            'PADDING_TITULO_ABA',
            'PANEL',
            'SIDEBAR',
            'TAMANHO_APOIO',
            'TAMANHO_CORPO',
            'TAMANHO_SUBTITULO',
            'TAMANHO_TITULO_ABA',
            'TAMANHO_TITULO_HERO',
            'TAMANHO_TITULO_MODAL',
            'TEXT',
            'WHITE',
            'safe_window_geometry',
            'safe_window_size',
        }
        self.assertTrue(expected.issubset(imported))

    def test_preserves_key_labels_and_safety_texts(self):
        for text in (
            'Sem exclusão • sem formatação',
            'BACKUP NÃO VERIFICADO NESTA TELA',
            'Primeiro uso guiado  →',
            'Depois de formatar  →',
            'Somente os arquivos marcados no C: serão copiados.',
            'O app não apaga nenhum arquivo dos outros discos e unidades.',
            'Verificação de hardware e discos',
            'Plano de continuidade após o Windows',
        ):
            self.assertIn(text, SOURCE)


@unittest.skipIf(tk is None or ttk is None, 'tkinter indisponível neste ambiente')
class AppUiTkTests(unittest.TestCase):
    """Testes reais de widgets de `app.py` (sem tocar em discos ou perfis reais)."""

    def _new_root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk indisponível neste ambiente: {exc}')
        root.withdraw()
        return track_tk_root(self, root)

    def test_inventory_treeview_uses_min_height_and_safe_geometry(self):
        import app

        root = self._new_root()

        class _Host:
            def __init__(self, parent):
                self.inventory = ttk.Frame(parent)
                self.inventory.pack(fill='both', expand=True)
                self.review = ttk.Frame(parent)

            def label(self, parent, text, size=TAMANHO_CORPO, fg=TEXT, **kwargs):
                return tk.Label(
                    parent, text=text, font=(FONTE_UI, size), fg=fg,
                    bg=PANEL, justify='left', anchor='w', **kwargs,
                )

            def add_folder(self):
                pass

            def add_file(self):
                pass

            def navigate(self, _page):
                pass

            def set_choice(self, _choice):
                pass

            def remove_personal_item(self):
                pass

        host = _Host(root)
        app.App._build_inventory(host)
        root.update_idletasks()

        self.assertEqual(int(host.tree.cget('height')), ALTURA_MINIMA_TABELA_LINHAS)
        self.assertEqual(safe_window_geometry(1400, 875, 1280, 720), '1200x640')
        self.assertEqual(safe_window_size(1050, 660, 1280, 720, min_w=640, min_h=480), (1050, 640))


if __name__ == '__main__':
    unittest.main()
