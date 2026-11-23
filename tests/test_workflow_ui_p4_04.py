"""P4-04 (Fatia 18): testes de aparência e escala visual em `workflow_ui.py`."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from tests.tk_helpers import track_tk_root
from ui_scale import safe_window_size, safe_wraplength

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover - servidor Linux sem tkinter
    tk = None
    ttk = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'workflow_ui.py').read_text(encoding='utf-8')


class WorkflowUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_duplicate_colors_or_fonts(self):
        self.assertNotIn("'Segoe UI'", SOURCE)
        self.assertNotIn('"Segoe UI"', SOURCE)
        self.assertNotIn("'Consolas'", SOURCE)
        self.assertNotIn('"Consolas"', SOURCE)
        for hex_color in ('#0C1220', '#192438', '#EFF4FF', '#9CAAC0', '#9C85FF', '#2B3952', '#5DDEB1', '#F3BE67'):
            self.assertNotIn(hex_color, SOURCE)

        tree = ast.parse(SOURCE)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui_scale':
                imported.update(alias.name for alias in node.names)

        expected = {
            'ACCENT',
            'AMBER',
            'BG',
            'BORDER',
            'ESPACO_DENTRO_GRUPO',
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_M',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_MONO',
            'FONTE_UI',
            'GREEN',
            'MUTED',
            'PADDING_CAIXA_TEXTO',
            'PADDING_DIALOGO',
            'PADDING_PAINEL_COMPACTO',
            'PANEL',
            'TAMANHO_APOIO',
            'TAMANHO_CORPO',
            'TAMANHO_SUBTITULO',
            'TAMANHO_TITULO_ABA',
            'TAMANHO_TITULO_HERO',
            'TAMANHO_TITULO_MODAL',
            'TEXT',
            'safe_window_geometry',
            'safe_window_size',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported))

    def test_bottom_bars_packed_before_expandable_widgets(self):
        self.assertLess(
            SOURCE.index("actions.pack(side='bottom', fill='x'"),
            SOURCE.index("tablebox.pack(fill='both', expand=True)"),
        )
        self.assertLess(
            SOURCE.index("bottom.pack(side='bottom', fill='x'"),
            SOURCE.index("tiles.pack(fill='both', expand=True)"),
        )
        self.assertLess(
            SOURCE.index("footer.pack(side='bottom', fill='x'"),
            SOURCE.index("area.pack(fill='both', expand=True)"),
        )


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _collect_texts(widget):
    texts: list[str] = []
    for child in _walk_widgets(widget):
        try:
            text = child.cget('text')
        except tk.TclError:
            text = ''
        if text:
            texts.append(str(text))
    return texts


def _find_button(widget, label):
    for child in _walk_widgets(widget):
        if isinstance(child, ttk.Button) and str(child.cget('text')) == label:
            return child
    return None


def _assert_widget_visible_in(testcase, widget, container, label):
    testcase.assertTrue(widget.winfo_ismapped(), f'{label}: nao mapeado')
    w_x1 = widget.winfo_rootx()
    w_y1 = widget.winfo_rooty()
    w_x2 = w_x1 + widget.winfo_width()
    w_y2 = w_y1 + widget.winfo_height()
    c_x1 = container.winfo_rootx()
    c_y1 = container.winfo_rooty()
    c_x2 = c_x1 + container.winfo_width()
    c_y2 = c_y1 + container.winfo_height()
    testcase.assertGreaterEqual(w_x1, c_x1, f'{label}: cortado a esquerda ({w_x1} < {c_x1})')
    testcase.assertGreaterEqual(w_y1, c_y1, f'{label}: cortado acima ({w_y1} < {c_y1})')
    testcase.assertLessEqual(w_x2, c_x2, f'{label}: cortado a direita ({w_x2} > {c_x2})')
    testcase.assertLessEqual(w_y2, c_y2, f'{label}: cortado abaixo ({w_y2} > {c_y2})')


class _FakeApp:
    def __init__(self, root):
        self._root = root
        self.overview = ttk.Frame(root)
        self.preservation = ttk.Frame(root)
        self.installation = ttk.Frame(root)
        self.home = ttk.Frame(root)
        self.review = ttk.Frame(root)
        self.diagnostic = ttk.Frame(root)
        self.recovery = ttk.Frame(root)
        self.choices = {}
        self.catalog_choices = {}
        self.catalog_items = {}
        self.deep_scan_report = {}
        self.scan_reports_by_drive = {}
        self.cleanup_candidates = ()
        self.last_preservation_audit = None
        self.navigated = []

    def navigate(self, target):
        self.navigated.append(target)

    def import_previous_choices(self):
        return None

    def _on_change(self):
        return None

    def winfo_toplevel(self):
        return self._root


class WorkflowUiTkTests(unittest.TestCase):
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

    def test_overview_preservation_and_installation_render_real_widgets(self):
        root = self._new_root()
        from workflow_ui import build_installation, build_overview, build_preservation

        app = _FakeApp(root)
        long_path = 'C:\\Jogos\\SemEspacos\\' + ('SubpastaMuitoLonga_' * 10) + 'arquivo.dat'
        app.choices = {long_path: 'keep'}
        app.catalog_items = {
            'game-1': {
                'id': 'game-1',
                'name': 'Jogo com Ação & Símbolos — Edição Especial (2026)',
                'kind': 'game',
                'path': long_path,
                'volume': 'D:',
            }
        }
        app.catalog_choices = {'game-1': 'keep'}

        build_overview(app)
        build_preservation(app)
        build_installation(app)

        app.overview.pack(fill='both', expand=True)
        root.deiconify()
        root.geometry('960x680')
        root.update()

        overview_texts = _collect_texts(app.overview)
        self.assertIn('Uma reinstalação organizada, sem surpresas', overview_texts)
        self.assertIsNotNone(_find_button(app.overview, 'Abrir etapa  →'))

        app.overview.pack_forget()
        app.preservation.pack(fill='both', expand=True)
        root.update()

        preservation_texts = _collect_texts(app.preservation)
        self.assertIn('O que deve permanecer no computador?', preservation_texts)
        for btn_label in (
            'Atualizar plano',
            'Importar escolhas da versão anterior',
            'Explorar discos',
            'Exportar JSON',
            'Revisar erros de varredura',
            'Retirar do backup (não apaga)',
            'Próximo: revisar backup dos arquivos escolhidos →',
        ):
            self.assertIsNotNone(_find_button(app.preservation, btn_label), f'Botão ausente: {btn_label}')

        app.preservation.pack_forget()
        app.installation.pack(fill='both', expand=True)
        root.update()

        install_texts = _collect_texts(app.installation)
        self.assertIn('Preparação da instalação limpa do Windows', install_texts)
        for btn_label in (
            'Revisar preservação',
            'Diagnóstico dos discos',
            'Recuperação depois do Windows',
        ):
            btn = _find_button(app.installation, btn_label)
            self.assertIsNotNone(btn, f'Botão ausente: {btn_label}')
            _assert_widget_visible_in(self, btn, app.installation, btn_label)

    def test_dialogs_preflight_and_scan_gaps_keep_buttons_visible_at_minsize(self):
        root = self._new_root()
        from workflow_ui import show_c_preflight, show_scan_gaps

        long_c_path = 'C:\\Users\\Demo\\' + ('PastaExtensa_' * 14) + 'save.bin'
        win_pre = show_c_preflight(root, {'requires_verified_backup': [long_c_path]})
        try:
            win_pre.update()
            self.assertEqual(tuple(int(x) for x in win_pre.resizable()), (1, 1))
            expected_min = safe_window_size(
                640, 420, win_pre.winfo_screenwidth(), win_pre.winfo_screenheight()
            )
            self.assertEqual(win_pre.minsize(), expected_min)

            win_pre.geometry(f'{expected_min[0]}x{expected_min[1]}')
            win_pre.update()
            for btn_label in ('Exportar conferência JSON', 'Fechar'):
                btn = _find_button(win_pre, btn_label)
                self.assertIsNotNone(btn, f'Botão ausente: {btn_label}')
                _assert_widget_visible_in(self, btn, win_pre, btn_label)

            # Confere que o wraplength acompanha a largura do container ao redimensionar.
            frame = win_pre.winfo_children()[0]
            frame.event_generate('<Configure>', width=520)
            win_pre.update_idletasks()
            wrapped = [
                int(w.cget('wraplength'))
                for w in frame.winfo_children()
                if isinstance(w, ttk.Label) and int(w.cget('wraplength') or 0) > 0
            ]
            self.assertTrue(wrapped)
            self.assertTrue(all(w == safe_wraplength(520) for w in wrapped))
        finally:
            win_pre.destroy()

        report = {
            'roots': ['C:\\'],
            'errors': [{'path': long_c_path, 'reason': 'Acesso negado para leitura de metadados'}],
            'skipped': [{'path': 'D:\\Jogos\\' + ('X' * 190), 'reason': 'Ignorado por regra de tamanho'}],
        }
        win_gaps = show_scan_gaps(root, report=report)
        try:
            win_gaps.update()
            self.assertEqual(tuple(int(x) for x in win_gaps.resizable()), (1, 1))
            expected_min = safe_window_size(
                640, 420, win_gaps.winfo_screenwidth(), win_gaps.winfo_screenheight()
            )
            self.assertEqual(win_gaps.minsize(), expected_min)

            win_gaps.geometry(f'{expected_min[0]}x{expected_min[1]}')
            win_gaps.update()
            for btn_label in ('Mostrar mais 200', 'Exportar relatório JSON', 'Fechar'):
                btn = _find_button(win_gaps, btn_label)
                self.assertIsNotNone(btn, f'Botão ausente: {btn_label}')
                _assert_widget_visible_in(self, btn, win_gaps, btn_label)
        finally:
            win_gaps.destroy()


if __name__ == '__main__':
    unittest.main()
