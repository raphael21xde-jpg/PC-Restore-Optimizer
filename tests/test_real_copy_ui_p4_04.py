"""P4-04 (Fatia 4): testes de `real_copy_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
import re
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
SOURCE = (ROOT / 'real_copy_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class RealCopyUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('padding=14', SOURCE)
        self.assertNotIn('padx=(0, 7)', SOURCE)

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
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'ESPACO_ROTULO_CAMPO',
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

    def test_bottom_bars_packed_before_text_box_and_texts_preserved(self):
        actions_pos = SOURCE.index("actions.pack(side='bottom', fill='x'")
        tools_pos = SOURCE.index("tools.pack(side='bottom', fill='x'")
        box_pos = SOURCE.index("box.pack(fill='both', expand=True)")
        self.assertLess(actions_pos, box_pos)
        self.assertLess(tools_pos, box_pos)

        self.assertIn('Cópia protegida para outro disco', SOURCE)
        self.assertIn('Escolha ao menos uma pasta de origem e uma pasta de destino', SOURCE)
        self.assertIn('O aplicativo está aberto como administrador', SOURCE)
        for label in (
            'Adicionar origem',
            'Adicionar destino',
            'Limpar escolhas',
            'Ler discos',
            'Sim, pode ler',
            'Não',
            'Confirmo esta cópia',
            'Copiar agora',
            'Cancelar',
            'Fechar',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class RealCopyUiTkTests(unittest.TestCase):
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

    def test_dark_theme_geometry_and_bad_data_layout(self):
        root = self._new_root()
        import real_copy_ui as rcu

        long_source = 'C:\\Dados\\' + ('Pasta_Muito_Longa_Com_Acentos_e_Símbolos_' * 4) + 'fim'
        dlg = rcu.show_real_copy(
            root,
            collector=lambda: [],
            ask_folder=lambda _parent, _title: long_source,
            elevated_probe=lambda: False,
        )
        dlg.update_idletasks()

        self.assertEqual(dlg.minsize(), (680, 460))

        texts = [w for w in _walk_widgets(dlg) if isinstance(w, tk.Text)]
        self.assertEqual(len(texts), 1)
        txt = texts[0]
        self.assertEqual(txt.cget('bg'), ui_scale.COR_PAINEL)
        self.assertEqual(txt.cget('fg'), ui_scale.COR_TEXTO)
        self.assertEqual(txt.cget('selectbackground'), ui_scale.COR_SELECAO)
        self.assertEqual(txt.cget('highlightbackground'), ui_scale.COR_BORDA)
        self.assertEqual(int(txt.cget('padx')), ui_scale.PADDING_CAIXA_TEXTO[0])
        self.assertEqual(int(txt.cget('pady')), ui_scale.PADDING_CAIXA_TEXTO[1])

        dlg.real_copy_buttons['Adicionar origem'].invoke()
        self.assertEqual(dlg.real_copy_state['sources'], [long_source])
        self.assertIn('Origens escolhidas: 1 pasta(s)', dlg.real_copy_choices.get())

    def test_elevated_notice_and_disabled_read_button(self):
        root = self._new_root()
        import real_copy_ui as rcu

        dlg = rcu.show_real_copy(
            root,
            collector=lambda: [],
            elevated_probe=lambda: True,
        )
        dlg.update_idletasks()

        labels = [
            str(w.cget('text'))
            for w in _walk_widgets(dlg)
            if isinstance(w, ttk.Label)
        ]
        self.assertTrue(any(rcu.ADMIN_TEXT in text for text in labels))
        self.assertIn('disabled', dlg.real_copy_buttons['Ler discos'].state())
