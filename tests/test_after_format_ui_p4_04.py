"""P4-04 (Fatia 8): testes de `after_format_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
import json
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
SOURCE = (ROOT / 'after_format_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class AfterFormatUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('padding=14', SOURCE)
        self.assertNotIn('padx=6', SOURCE)
        self.assertNotIn('pady=(6, 6)', SOURCE)

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
            'ESPACO_FINO',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_UI',
            'PADDING_CAIXA_TEXTO',
            'PADDING_DIALOGO',
            'TAMANHO_CORPO',
            'TAMANHO_TITULO_MODAL',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_controls_packed_before_grid_and_texts_preserved(self):
        close_pos = SOURCE.index("close_btn.pack(side='bottom'")
        guide_pos = SOURCE.index("guide.pack(side='bottom'")
        grid_pos = SOURCE.index("grid.pack(fill='both', expand=True)")
        self.assertLess(close_pos, grid_pos)
        self.assertLess(guide_pos, grid_pos)

        self.assertIn('Depois de formatar: passo a passo', SOURCE)
        self.assertIn('Unidades deste computador agora (só leitura)', SOURCE)
        for label in ('Abrir', 'Feito', 'Pular', 'Fechar'):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class AfterFormatUiTkTests(unittest.TestCase):
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

    def test_dark_theme_minsize_and_bad_data_guide(self):
        root = self._new_root()
        import after_format_ui as afu

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / 'backup'
            backup_dir.mkdir()
            manifest = backup_dir / 'manifest.json'
            manifest.write_text(json.dumps({'backup_id': 'test-1'}), encoding='utf-8')
            long_guidance = 'Orientação_' + ('Texto_Longo_Com_Acentos_e_Símbolos_' * 6) + 'fim'
            fake_drives = {
                'drives': [
                    {
                        'letter': 'D:',
                        'type': 'Fixo',
                        'total_text': '100 GiB',
                        'free_text': '50 GiB',
                        'windows': False,
                    },
                ],
                'warnings': [],
                'guidance': long_guidance,
            }
            dlg = afu.show_after_format(
                root,
                manifest=manifest,
                base=Path(tmp),
                checker=lambda _m, _c: (fake_drives, ''),
            )
            iters = 0
            while dlg.after_format_state['busy'] and iters < 100:
                dlg.update()
                root.after(20)
                iters += 1
            dlg.update_idletasks()

            self.assertEqual(dlg.minsize(), (720, 520))

            guide = dlg.after_format_guide
            self.assertEqual(guide.cget('bg'), ui_scale.COR_PAINEL)
            self.assertEqual(guide.cget('fg'), ui_scale.COR_TEXTO)
            self.assertEqual(guide.cget('selectbackground'), ui_scale.COR_SELECAO)
            self.assertEqual(guide.cget('highlightbackground'), ui_scale.COR_BORDA)
            self.assertEqual(int(guide.cget('padx')), ui_scale.PADDING_CAIXA_TEXTO[0])
            self.assertEqual(int(guide.cget('pady')), ui_scale.PADDING_CAIXA_TEXTO[1])
            self.assertIn(long_guidance, guide.get('1.0', 'end-1c'))

            buttons = {
                str(w.cget('text'))
                for w in _walk_widgets(dlg)
                if isinstance(w, ttk.Button)
            }
            for label in ('Abrir', 'Feito', 'Pular', 'Fechar'):
                self.assertIn(label, buttons)
