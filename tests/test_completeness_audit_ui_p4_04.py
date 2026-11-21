"""Testes da fatia 15 do P4-04: escala visual em completeness_audit_ui_v067 e v068."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
    from tkinter import ttk
    import completeness_audit_ui_v067 as ui_v067
    import completeness_audit_ui_v068 as ui_v068
except ImportError:  # pragma: no cover - ambiente sem tkinter
    tk = None
    ttk = None
    ui_v067 = None
    ui_v068 = None

from ui_scale import safe_window_size
from tests.tk_helpers import track_tk_root


ROOT = Path(__file__).resolve().parent.parent


def _collect_buttons(widget):
    buttons = []
    for child in widget.winfo_children():
        if ttk is not None and isinstance(child, (ttk.Button, tk.Button)):
            buttons.append(child)
        buttons.extend(_collect_buttons(child))
    return buttons


def _synthetic_report():
    long_path = 'C:\\Dados\\Pasta_muito_longa_com_acentos_ação_é_ç\\' + ('sub_' * 40) + 'arquivo.txt'
    return {
        'counts': {
            'locations_reviewed': 1,
            'locations_needing_review': 0,
            'c_scan_errors': 0,
            'c_scan_skipped': 0,
        },
        'candidate_locations': [
            {
                'name': 'Documentos',
                'path': long_path,
                'status': 'OK',
                'category': 'Perfil',
                'detail': 'Caminho sintético longo para teste',
            }
        ],
        'scan_c': {'errors': [], 'skipped': []},
        'boot': {'status': 'NAO_VERIFICADO', 'note': 'Teste sintético sem disco real.'},
        'disk_evidence': {'data': {'disks': [], 'efi_partitions': [], 'errors': []}},
        'recovery_map': [],
        'manual_tasks': ['Conferir lista sintética.'],
    }


class CompletenessAuditUiStaticTests(unittest.TestCase):
    def test_v067_uses_ui_scale_tokens_and_removes_raw_values(self):
        src = (ROOT / 'completeness_audit_ui_v067.py').read_text(encoding='utf-8')
        self.assertIn('from ui_scale import', src)
        for token in (
            'PADDING_DIALOGO',
            'PADDING_ABA_NOTEBOOK',
            'PADDING_CAIXA_TEXTO',
            'ESPACO_ENTRE_BOTOES',
            'COR_ALERTA',
            'COR_PAINEL',
            'COR_TEXTO',
            'safe_window_geometry',
            'safe_wraplength',
        ):
            self.assertIn(token, src)
        for old in (r'\bpadding=15\b', r'\bpadding=8\b', r'\bpady=\(0, 5\)', r'#F3BE67', r'#192438', r'#EFF4FF'):
            self.assertIsNone(re.search(old, src), f'Valor antigo ainda presente em v067: {old}')

    def test_v068_uses_ui_scale_tokens_and_removes_raw_values(self):
        src = (ROOT / 'completeness_audit_ui_v068.py').read_text(encoding='utf-8')
        self.assertIn('from ui_scale import', src)
        for token in (
            'PADDING_DIALOGO',
            'PADDING_ABA_NOTEBOOK',
            'PADDING_CAIXA_TEXTO',
            'ESPACO_ENTRE_BOTOES',
            'COR_ALERTA',
            'COR_PAINEL',
            'COR_TEXTO',
            'safe_window_geometry',
            'safe_wraplength',
        ):
            self.assertIn(token, src)
        for old in (
            r'\bpadding=15\b',
            r'\bpadding=8\b',
            r'\bpadx=4\b',
            r'\bpadx=6\b',
            r'\bpady=\(0, 9\)',
            r'#F3BE67',
            r'#192438',
            r'#EFF4FF',
        ):
            self.assertIsNone(re.search(old, src), f'Valor antigo ainda presente em v068: {old}')


class CompletenessAuditUiTkTests(unittest.TestCase):
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
        root.home = object()
        root.navigate = lambda _target: None
        return root

    def _assert_buttons_visible_at_minsize(self, win, expected_min, expected_texts=()):
        min_w, min_h = win.minsize()
        self.assertEqual((min_w, min_h), expected_min)
        win.geometry(f'{min_w}x{min_h}')
        win.update()
        win_w = win.winfo_width()
        win_h = win.winfo_height()
        buttons = _collect_buttons(win)
        self.assertGreater(len(buttons), 0)
        mapped_texts = set()
        for btn in buttons:
            if not btn.winfo_ismapped():
                continue
            mapped_texts.add(btn.cget('text'))
            bx = btn.winfo_rootx() - win.winfo_rootx()
            by = btn.winfo_rooty() - win.winfo_rooty()
            self.assertGreaterEqual(bx, 0, f'Botão fora à esquerda: {btn.cget("text")}')
            self.assertGreaterEqual(by, 0, f'Botão fora no topo: {btn.cget("text")}')
            self.assertLessEqual(bx + btn.winfo_width(), win_w + 2, f'Botão cortado à direita: {btn.cget("text")}')
            self.assertLessEqual(by + btn.winfo_height(), win_h + 2, f'Botão cortado embaixo: {btn.cget("text")}')
        for text in expected_texts:
            self.assertIn(text, mapped_texts, f'Botão esperado não está visível: {text}')

    def test_v067_minimum_size_keeps_action_buttons_visible(self):
        root = self._new_root()
        with mock.patch.object(ui_v067, 'build_completeness_report', return_value=_synthetic_report()):
            win = ui_v067.show_completeness_audit(root, plan={})
            win.update()
            expected_min = safe_window_size(
                870, 590, win.winfo_screenwidth(), win.winfo_screenheight(), min_w=640, min_h=480
            )
            self._assert_buttons_visible_at_minsize(
                win,
                expected_min,
                expected_texts=('Exportar auditoria JSON', 'Ver escolhas em Meu Computador', 'Fechar'),
            )
            win.destroy()

    def test_v068_minimum_size_keeps_action_buttons_visible(self):
        root = self._new_root()
        with (
            mock.patch.object(ui_v068, 'build_completeness_report', return_value=_synthetic_report()),
            mock.patch.object(ui_v068, 'collect_disk_evidence_068', return_value={'data': {'disks': [], 'efi_partitions': [], 'errors': []}}),
            mock.patch.object(ui_v068, 'classify_boot_068', return_value={'status': 'NAO_VERIFICADO', 'note': 'Teste'}),
        ):
            win = ui_v068.show_completeness_audit(root, plan={})
            win.update()
            expected_min = safe_window_size(
                870, 590, win.winfo_screenwidth(), win.winfo_screenheight(), min_w=640, min_h=480
            )
            self._assert_buttons_visible_at_minsize(
                win,
                expected_min,
                expected_texts=('Exportar auditoria JSON', 'Ver escolhas em Meu Computador', 'Fechar'),
            )
            win.destroy()


if __name__ == '__main__':
    unittest.main()
