"""Testes da fatia 16 do P4-04: escala visual em selective_backup_ui.py."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk
    import selective_backup_ui as ui_sel
except ImportError:  # pragma: no cover - ambiente sem tkinter
    tk = None
    ttk = None
    ui_sel = None

from ui_scale import PADDING_DIALOGO, safe_window_size, safe_wraplength
from tests.tk_helpers import track_tk_root


ROOT = Path(__file__).resolve().parent.parent


def _collect_buttons(widget):
    buttons = []
    for child in widget.winfo_children():
        if ttk is not None and isinstance(child, (ttk.Button, tk.Button)):
            buttons.append(child)
        buttons.extend(_collect_buttons(child))
    return buttons


class SelectiveBackupUiStaticTests(unittest.TestCase):
    def test_selective_backup_ui_uses_ui_scale_tokens_and_removes_raw_values(self):
        src = (ROOT / 'selective_backup_ui.py').read_text(encoding='utf-8')
        self.assertIn('from ui_scale import', src)
        for token in (
            'PADDING_DIALOGO',
            'PADDING_ABA_NOTEBOOK',
            'PADDING_CAIXA_TEXTO',
            'ESPACO_ENTRE_BOTOES',
            'COR_ALERTA',
            'COR_DESTAQUE',
            'COR_PAINEL',
            'COR_TEXTO',
            'safe_window_size',
            'safe_window_geometry',
            'safe_wraplength',
        ):
            self.assertIn(token, src)
        for old in (
            r'\bpadding=18\b',
            r'\bpadding=\(12,\s*5\)',
            r'\bpadx=\(8,\s*0\)',
            r'#F3BE67',
            r'#192438',
            r'#EFF4FF',
            r'#9C85FF',
        ):
            self.assertIsNone(re.search(old, src), f'Valor antigo ainda presente: {old}')


class SelectiveBackupUiTkTests(unittest.TestCase):
    def _new_root(self):
        if tk is None:
            self.skipTest('tkinter indisponível neste ambiente')
        try:
            root = track_tk_root(self, tk.Tk())
        except tk.TclError as exc:
            self.skipTest(f'display Tk indisponível: {exc}')
        try:
            root.attributes('-alpha', 0.0)
        except tk.TclError:
            pass
        root.geometry('1x1+0+0')
        root.choices = {}
        return root

    def test_minimum_size_keeps_footer_buttons_visible_and_updates_wraplength(self):
        root = self._new_root()
        long_path = 'C:\\Dados\\Pasta_muito_longa_com_acentos_ação_é_ç\\' + ('sub_' * 45) + 'save.db'
        plan = {'requires_verified_backup': [long_path, long_path + '.bak']}
        win = ui_sel.show_selective_backup(root, plan)
        win.update()

        expected_min = safe_window_size(
            640, 420, win.winfo_screenwidth(), win.winfo_screenheight(), min_w=360, min_h=280
        )
        min_w, min_h = win.minsize()
        self.assertEqual((min_w, min_h), expected_min)

        win.geometry(f'{min_w}x{min_h}')
        win.update()
        win_w = win.winfo_width()
        win_h = win.winfo_height()

        buttons = _collect_buttons(win)
        mapped_texts = set()
        for btn in buttons:
            if not btn.winfo_ismapped():
                continue
            mapped_texts.add(btn.cget('text'))
            if btn.cget('text') in ('Exportar relatório', 'Cancelar operação'):
                bx = btn.winfo_rootx() - win.winfo_rootx()
                by = btn.winfo_rooty() - win.winfo_rooty()
                self.assertGreaterEqual(bx, 0, f'Botão fora à esquerda: {btn.cget("text")}')
                self.assertGreaterEqual(by, 0, f'Botão fora no topo: {btn.cget("text")}')
                self.assertLessEqual(bx + btn.winfo_width(), win_w + 2, f'Botão cortado à direita: {btn.cget("text")}')
                self.assertLessEqual(by + btn.winfo_height(), win_h + 2, f'Botão cortado embaixo: {btn.cget("text")}')

        self.assertIn('Exportar relatório', mapped_texts)
        self.assertIn('Cancelar operação', mapped_texts)

        # Verifica atualização de wraplength no container e filtro de event.widget.
        viewport = next(c for c in win.winfo_children() if isinstance(c, tk.Canvas))
        container = viewport.winfo_children()[0]
        wrapped_labels = [
            child for child in container.winfo_children()
            if isinstance(child, ttk.Label) and int(str(child.cget('wraplength') or 0)) > 0
        ]
        self.assertGreaterEqual(len(wrapped_labels), 4)
        expected_wrap = safe_wraplength(container.winfo_width(), padding=PADDING_DIALOGO)
        for lbl in wrapped_labels:
            self.assertEqual(int(str(lbl.cget('wraplength'))), expected_wrap)

        other_widget = next(c for c in container.winfo_children() if isinstance(c, ttk.Frame))
        other_widget.event_generate('<Configure>', width=200)
        win.update()
        for lbl in wrapped_labels:
            self.assertEqual(int(str(lbl.cget('wraplength'))), expected_wrap)

        win.destroy()


if __name__ == '__main__':
    unittest.main()
