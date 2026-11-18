"""P4-04 (Fatia 10): testes de `winget_programs_ui.py` com `ui_scale`."""
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
SOURCE = (ROOT / 'winget_programs_ui.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')


class WingetProgramsUiStaticTests(unittest.TestCase):
    """Conferências estáticas que rodam mesmo com `sys.modules['tkinter'] = None`."""

    def test_uses_ui_scale_tokens_and_no_old_literals(self):
        self.assertEqual(HEX_COLOR_RE.findall(SOURCE), [])
        self.assertNotIn("'Segoe UI'", SOURCE)
        for old_literal in (
            'padding=14',
            'padx=(0, 7)',
            'padx=(7, 7)',
            'padx=(7, 0)',
            'pady=(6, 6)',
            'pady=(0, 4)',
            'pady=(0, 8)',
            'pady=(0, 10)',
            'pady=(8, 0)',
            'pady=(4, 6)',
            'pady=(0, 6)',
            'pady=(6, 4)',
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
            'COR_SELECAO',
            'COR_TEXTO',
            'ESPACO_ENTRE_BOTOES',
            'ESPACO_MINIMO',
            'ESPACO_P',
            'FONTE_MONO',
            'FONTE_UI',
            'PADDING_CAIXA_TEXTO',
            'PADDING_DIALOGO',
            'TAMANHO_CORPO',
            'TAMANHO_SUBTITULO',
            'safe_window_geometry',
            'safe_wraplength',
        }
        self.assertTrue(expected.issubset(imported_from_ui_scale))

    def test_bottom_controls_packed_before_expandable_widgets_and_texts_preserved(self):
        # build_confirm: buttons antes de box
        self.assertLess(
            SOURCE.index("buttons.pack(side='bottom', fill='x')"),
            SOURCE.index("box.pack(fill='both', expand=True"),
        )
        # show_results: Fechar antes de table
        self.assertLess(
            SOURCE.index("ttk.Button(frame, text='Fechar', command=win.destroy).pack("),
            SOURCE.index("table.pack(fill='both', expand=True)"),
        )
        # show_programs: tools e counter_label antes de grid
        self.assertLess(
            SOURCE.index("tools.pack(side='bottom', fill='x')"),
            SOURCE.index("grid.pack(fill='both', expand=True)"),
        )
        self.assertLess(
            SOURCE.index("counter_label.pack(side='bottom', fill='x'"),
            SOURCE.index("grid.pack(fill='both', expand=True)"),
        )

        for label in (
            'Confirmar instalação',
            'Resultado da instalação',
            'Programas do backup',
            'Marcar categoria',
            'Marcar tudo',
            'Desmarcar tudo',
            'Instalar marcados…',
            'Salvar lista agora',
            'Fechar',
        ):
            self.assertIn(label, SOURCE)


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class WingetProgramsUiTkTests(unittest.TestCase):
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

    def test_confirm_dialog_dark_box_and_minsize(self):
        root = self._new_root()
        import winget_programs_ui as wui

        long_id = 'Fabricante.AplicativoMuitoLongo_ComAcentos_ção_é_' + ('X' * 140)
        win, state = wui.build_confirm(root, ['7zip.7zip', long_id])
        self.addCleanup(lambda: win.destroy() if win.winfo_exists() else None)
        win.update_idletasks()

        self.assertEqual(state['ok'], False)
        self.assertEqual(win.minsize(), (460, 360))

        box = win.confirm_box
        self.assertEqual(box.cget('bg'), ui_scale.COR_PAINEL)
        self.assertEqual(box.cget('fg'), ui_scale.COR_TEXTO)
        self.assertEqual(box.cget('selectbackground'), ui_scale.COR_SELECAO)
        self.assertEqual(box.cget('highlightbackground'), ui_scale.COR_BORDA)
        self.assertEqual(int(box.cget('padx')), ui_scale.PADDING_CAIXA_TEXTO[0])
        self.assertEqual(int(box.cget('pady')), ui_scale.PADDING_CAIXA_TEXTO[1])
        self.assertIn(long_id, box.get('1.0', 'end-1c'))

        buttons = {
            str(w.cget('text'))
            for w in _walk_widgets(win)
            if isinstance(w, ttk.Button)
        }
        self.assertIn('Cancelar', buttons)
        self.assertIn('Instalar 2 programa(s)', buttons)

    def test_results_dialog_minsize_and_empty_or_long_results(self):
        root = self._new_root()
        import winget_programs_ui as wui

        long_msg = 'Resumo_' + ('detalhe_com_acentos_e_símbolos_' * 8)
        win = wui.show_results(
            root,
            {
                'message': long_msg,
                'results': [
                    {
                        'id': 'Vendor.LongPackage_' + ('A' * 120),
                        'status': 'instalado',
                        'explanation': 'Concluído com sucesso em caminho longo.',
                    },
                ],
            },
        )
        self.addCleanup(lambda: win.destroy() if win.winfo_exists() else None)
        win.update_idletasks()
        self.assertEqual(win.minsize(), (560, 340))

    def test_show_programs_minsize_and_loaded_state(self):
        root = self._new_root()
        import winget_programs as wp
        import winget_programs_ui as wui

        payload = {
            '$schema': 'https://aka.ms/winget-packages.schema.2.0.json',
            'CreationDate': '2026-10-21T10:00:00',
            'WinGetVersion': '1.9.0',
            'Sources': [{
                'SourceDetails': {
                    'Name': 'winget',
                    'Identifier': 'Microsoft.Winget.Source_x',
                    'Argument': 'https://cdn.winget.microsoft.com/cache',
                    'Type': 'Microsoft.PreIndexed.Package',
                },
                'Packages': [
                    {'PackageIdentifier': '7zip.7zip', 'Version': '24.08'},
                ],
            }],
        }

        def fake_runner(cmd):
            target = Path(cmd[cmd.index('--output') + 1])
            target.write_text(json.dumps(payload), encoding='utf-8')
            return 0, ''

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / 'backup'
            backup_dir.mkdir()
            (backup_dir / 'manifest.json').write_text('{"status": "concluido"}', encoding='utf-8')
            saved = wp.save_export(backup_dir, runner=fake_runner, executable='winget')
            self.assertEqual(saved['status'], 'salvo', saved)

            dlg = wui.show_programs(root, backup_dir, elevated_probe=lambda: False)
            self.addCleanup(lambda: dlg.destroy() if dlg.winfo_exists() else None)
            iters = 0
            while dlg.program_state['loading'] and iters < 100:
                dlg.update()
                root.after(20)
                iters += 1
            dlg.update_idletasks()

            self.assertEqual(dlg.minsize(), (640, 440))
            self.assertTrue(dlg.program_state['loaded'])
            buttons = {
                str(w.cget('text'))
                for w in _walk_widgets(dlg)
                if isinstance(w, ttk.Button)
            }
            for label in ('Marcar categoria', 'Marcar tudo', 'Desmarcar tudo', 'Instalar marcados…', 'Fechar'):
                self.assertIn(label, buttons)
