"""P4-04 (Fatia 17): testes de `deep_discovery_ui.py` com `ui_scale`."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.tk_helpers import track_tk_root
from ui_scale import (
    COR_ALERTA,
    COR_DESTAQUE,
    COR_GRADE_GRAFICO,
    COR_PAINEL,
    COR_SELECAO,
    COR_TEXTO,
    PADDING_DIALOGO,
    safe_window_size,
    safe_wraplength,
)

try:
    import tkinter as tk
    from tkinter import ttk
    import deep_discovery_ui
except ImportError:  # pragma: no cover - servidor Linux sem tkinter
    tk = None
    ttk = None
    deep_discovery_ui = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'deep_discovery_ui.py').read_text(encoding='utf-8')


class DeepDiscoveryUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('"Segoe UI"', SOURCE)
        for old_literal in (
            '#192438',
            '#EFF4FF',
            '#9C85FF',
            '#F3BE67',
            '#394C75',
            '#334155',
            'padding=12',
            'padding=18',
            'padding=5',
            'padx=4',
            'padx=5',
            'padx=(0, 14)',
            'pady=6',
            'pady=7',
            'wraplength=1160',
            'wraplength=1150',
            'wraplength=800',
            'wraplength=770',
            'wraplength=765',
            'wraplength=710',
            "geometry('1220x800')",
            "geometry('850x460')",
            "geometry('850x610')",
        ):
            self.assertNotIn(old_literal, SOURCE)

        tree = ast.parse(SOURCE)
        imported_from_ui_scale: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported_from_ui_scale.update(alias.name for alias in node.names)

        expected = {
            'COR_ALERTA',
            'COR_DESTAQUE',
            'COR_GRADE_GRAFICO',
            'COR_PAINEL',
            'COR_SELECAO',
            'COR_TEXTO',
            'ESPACO_FINO',
            'ESPACO_M',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_UI',
            'PADDING_ABA_NOTEBOOK',
            'PADDING_DIALOGO',
            'TAMANHO_APOIO',
            'TAMANHO_CORPO',
            'TAMANHO_SUBTITULO',
            'TAMANHO_TITULO_ABA',
            'safe_window_geometry',
            'safe_window_size',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_preserves_labels_and_buttons(self):
        for label in (
            'Meu Computador — Seleção Inteligente Unificada',
            '+ Pasta pessoal',
            '+ Arquivo pessoal',
            'Adicionar pasta específica',
            'Ver todos os volumes',
            'Examinar unidades marcadas',
            'Cancelar (guardar resultado parcial)',
            'Importar inventário anterior',
            'Erros e exclusões',
            'Exportar relatório',
            'Manter selecionados',
            'Não preservar',
            'Candidato à remoção (prévia)',
            'Retirar sinalização',
            'Abrir ficha do jogo/app',
            'Ver Preservação →',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


@unittest.skipIf(tk is None or deep_discovery_ui is None, 'tkinter indisponível neste ambiente')
class DeepDiscoveryUiTkTests(unittest.TestCase):
    """Testes de janela Tk para `deep_discovery_ui.py`."""

    def _make_parent(self):
        root = track_tk_root(self, tk.Tk())
        root.withdraw()
        root.choices = {}
        root.catalog_items = {}
        root.approved_catalog_paths = {}
        root.cleanup_candidates = set()
        root.auto_save_paths = set()
        root.personal_paths = set()
        root.dest = tk.StringVar(master=root, value='')
        root.preservation = object()
        root.add_folder = lambda: None
        root.add_file = lambda: None
        root.navigate = lambda _target: None
        root._on_change = lambda: None
        return root

    def test_main_window_geometry_colors_and_wraplength_filter(self):
        root = self._make_parent()
        with patch('deep_discovery_ui.local_drives', return_value=['C:/', 'D:/']), \
             patch('deep_discovery_ui.choices_store.app_data_dir', return_value=Path('nao_existe_p4_04')):
            frame = deep_discovery_ui.show_deep_discovery(root)

        win = frame.winfo_toplevel()
        win.update()
        exp_w, exp_h = safe_window_size(1220, 800, win.winfo_screenwidth(), win.winfo_screenheight())
        exp_min_w, exp_min_h = safe_window_size(760, 520, win.winfo_screenwidth(), win.winfo_screenheight())
        self.assertEqual(win.winfo_geometry().split('+')[0], f'{exp_w}x{exp_h}')
        self.assertEqual(win.minsize(), (exp_min_w, exp_min_h))

        canvases = [w for w in _walk_widgets(frame) if isinstance(w, tk.Canvas)]
        self.assertEqual(len(canvases), 1)
        ring = canvases[0]
        self.assertEqual(ring.cget('bg').upper(), COR_PAINEL.upper())
        item_colors = {ring.itemcget(i, 'outline').upper() for i in ring.find_all() if ring.type(i) in ('oval', 'arc')}
        self.assertIn(COR_GRADE_GRAFICO.upper(), item_colors)
        self.assertIn(COR_DESTAQUE.upper(), item_colors)

        labels = [w for w in _walk_widgets(frame) if isinstance(w, ttk.Label)]
        intro = next(lbl for lbl in labels if 'Cada aba mostra somente arquivos' in str(lbl.cget('text')))

        # Evento em widget filho deve ser ignorado pelo filtro event.widget is not container
        before_wrap = int(str(intro.cget('wraplength')))
        intro.event_generate('<Configure>', width=350)
        win.update()
        self.assertEqual(int(str(intro.cget('wraplength'))), before_wrap)

        # Evento no container frame deve atualizar o wraplength
        frame.event_generate('<Configure>', width=640)
        win.update()
        self.assertEqual(int(str(intro.cget('wraplength'))), safe_wraplength(640, PADDING_DIALOGO))

    def test_volume_inventory_and_card_popups_use_ui_scale(self):
        root = self._make_parent()
        root.catalog_items = {
            'game:teste': {
                'name': 'Jogo Teste',
                'kind': 'game',
                'install_location': 'C:/Games/Teste',
                'observed_volumes': ['C:'],
                'paths': ['C:/Games/Teste/save.dat'],
                'possible_paths': ['C:/Games/Teste/extra.cfg'],
            }
        }
        with patch('deep_discovery_ui.local_drives', return_value=['C:/']), \
             patch('deep_discovery_ui.choices_store.app_data_dir', return_value=Path('nao_existe_p4_04')):
            frame = deep_discovery_ui.show_deep_discovery(root)

        win = frame.winfo_toplevel()
        win.update_idletasks()

        # Testar popup de inventário de volumes
        vol_btn = next(
            w for w in _walk_widgets(frame)
            if isinstance(w, ttk.Button) and str(w.cget('text')) == 'Ver todos os volumes'
        )
        fake_snapshot = {
            'status': 'ok',
            'notice': 'Aviso de teste sobre volumes.',
            'volumes': [
                {'drive_type': 'Fixo', 'volume_id': 'vol-1', 'mount_points': ['C:\\'],
                 'needs_manual_review': False, 'has_letter': True}
            ],
            'issues': (),
        }
        with patch('deep_discovery_ui.collect_volume_inventory', return_value=fake_snapshot):
            vol_btn.invoke()
            win.update_idletasks()

        popups = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(popups), 1)
        vol_popup = popups[0]
        texts = [w for w in _walk_widgets(vol_popup) if isinstance(w, tk.Text)]
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].cget('background').upper(), COR_PAINEL.upper())
        self.assertEqual(texts[0].cget('foreground').upper(), COR_TEXTO.upper())
        vol_popup.destroy()
        win.update_idletasks()

        # Testar popup da ficha do item
        trees = [w for w in _walk_widgets(frame) if isinstance(w, ttk.Treeview)]
        self.assertEqual(len(trees), 1)
        tree = trees[0]
        # Inserir um card sintético na árvore via refresh com report simulado
        root.deep_scan_report = {
            'schema': 'pcro-discovery-v1',
            'status': 'concluida',
            'roots': ['C:/'],
            'records': [{
                'app_id': 'game:teste',
                'app': 'Jogo Teste',
                'path': 'C:/Games/Teste/save.dat',
                'kind': 'Save/configuração associado ao jogo',
                'evidence': 'Catálogo de saves',
                'confidence': 'caminho identificado',
                'edition': None,
            }],
            'errors': [],
            'exclusions': [],
        }
        with patch('deep_discovery_ui.local_drives', return_value=['C:/']), \
             patch('deep_discovery_ui.choices_store.app_data_dir', return_value=Path('nao_existe_p4_04')):
            frame2 = deep_discovery_ui.show_deep_discovery(root)
        win2 = frame2.winfo_toplevel()
        win2.update_idletasks()
        tree2 = next(w for w in _walk_widgets(frame2) if isinstance(w, ttk.Treeview))
        # Selecionar o nó do card (filho do nó de categoria)
        selected_iid = None
        for cat_iid in tree2.get_children(''):
            children = tree2.get_children(cat_iid)
            if children:
                selected_iid = children[0]
                break
        self.assertIsNotNone(selected_iid)
        tree2.selection_set(selected_iid)
        card_btn = next(
            w for w in _walk_widgets(frame2)
            if isinstance(w, ttk.Button) and str(w.cget('text')) == 'Abrir ficha do jogo/app'
        )
        card_btn.invoke()
        win2.update_idletasks()

        card_popups = [w for w in win2.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(card_popups), 1)
        card_dialog = card_popups[0]
        known_text = next(w for w in _walk_widgets(card_dialog) if isinstance(w, tk.Text))
        self.assertEqual(known_text.cget('bg').upper(), COR_PAINEL.upper())
        self.assertEqual(known_text.cget('fg').upper(), COR_TEXTO.upper())
        listbox = next(w for w in _walk_widgets(card_dialog) if isinstance(w, tk.Listbox))
        self.assertEqual(listbox.cget('selectbackground').upper(), COR_SELECAO.upper())
        warn_lbl = next(
            w for w in _walk_widgets(card_dialog)
            if isinstance(w, ttk.Label) and 'Este painel não copia nem apaga arquivos.' in str(w.cget('text'))
        )
        self.assertEqual(str(warn_lbl.cget('foreground')).upper(), COR_ALERTA.upper())
        card_dialog.destroy()
        win2.update_idletasks()


if __name__ == '__main__':
    unittest.main()
