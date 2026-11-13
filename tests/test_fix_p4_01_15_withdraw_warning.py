"""FIX-P4-01-15: "Retirar do backup" e "NÃO será apagado" avisam que o item do disco do Windows se perde na formatação (R-88).

1. Ao lado do botão "Retirar do backup (não apaga)" (`workflow_ui.py`, ~linha 150), o texto
   `withdraw_choice_hint` lembra que, na unidade do Windows (`system_drive`), o item fica fora
   do backup e se perde quando o instalador formatar essa unidade.
2. Na confirmação ao retirar (`withdraw_confirmation_text`, ~linha 300), após
   "O arquivo original NÃO será apagado.", acrescenta a frase de perda na formatação
   **somente** para caminhos na unidade do Windows (`volume_of(path) == system_drive()`);
   caminhos em outras unidades (D:, E:, etc.) não trazem essa frase.

Importa apenas `workflow_texts` (sem `tkinter`) e não toca em discos reais.
"""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import workflow_texts

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'workflow_ui.py').read_text(encoding='utf-8')
TEXTS_SOURCE = (ROOT / 'workflow_texts.py').read_text(encoding='utf-8')


class WithdrawFromBackupWarningTests(unittest.TestCase):
    def test_hint_next_to_button_warns_about_system_drive_loss(self):
        hint_c = workflow_texts.withdraw_choice_hint('C:')
        self.assertIn('fica fora do backup', hint_c)
        self.assertIn('se perde quando o instalador formatar o C:', hint_c)
        with mock.patch.dict(
            workflow_texts.os.environ,
            {'SystemRoot': r'W:\Windows', 'SystemDrive': 'W:'},
            clear=False,
        ):
            hint_w = workflow_texts.withdraw_choice_hint()
        self.assertIn('no W:, o item fica fora do backup', hint_w)
        self.assertIn('se perde quando o instalador formatar o W:', hint_w)
        self.assertNotIn('C:', hint_w)
        self.assertNotIn(
            "'Selecione um caminho acima para retirar somente sua marcação.'",
            SOURCE,
        )
        self.assertIn('text=withdraw_choice_hint(sys_drive)', SOURCE)
        self.assertIn("text='Retirar do backup (não apaga)'", SOURCE)

    def test_confirmation_for_system_drive_path_includes_loss_warning(self):
        for c_path in (r'C:\Users\Teste\Documentos', 'c:/jogos/save'):
            text = workflow_texts.withdraw_confirmation_text(c_path, linked=False, drive='C:')
            self.assertIn('O arquivo original NÃO será apagado.', text)
            self.assertIn(workflow_texts.withdraw_loss_warning('C:'), text)
            self.assertIn('fica fora do backup', text)
            self.assertIn('se perde quando o instalador formatar o C:', text)
            self.assertIn('Nenhuma cópia, limpeza ou formatação será realizada.', text)

        with mock.patch.dict(
            workflow_texts.os.environ,
            {'SystemRoot': r'W:\Windows', 'SystemDrive': 'W:'},
            clear=False,
        ):
            text_w = workflow_texts.withdraw_confirmation_text(r'W:\Users\Teste\Save', linked=False)
            text_c_on_w = workflow_texts.withdraw_confirmation_text(r'C:\Jogos\Outro', linked=False)
        self.assertIn('No W:, este item fica fora do backup', text_w)
        self.assertIn('quando o instalador formatar o W:.', text_w)
        self.assertNotIn('C:', text_w)
        self.assertNotIn('fica fora do backup', text_c_on_w)

    def test_confirmation_for_non_system_drive_path_omits_loss_warning(self):
        for other_path in (r'D:\SteamLibrary\Game', 'E:/Arquivos'):
            text = workflow_texts.withdraw_confirmation_text(other_path, linked=False, drive='C:')
            self.assertIn('O arquivo original NÃO será apagado.', text)
            self.assertNotIn(workflow_texts.withdraw_loss_warning('C:'), text)
            self.assertNotIn('formatar o C:', text)
            self.assertIn('Nenhuma cópia, limpeza ou formatação será realizada.', text)

    def test_confirmation_preserves_linked_game_save_notice(self):
        text = workflow_texts.withdraw_confirmation_text(
            r'C:\Users\Teste\Save', linked=True, drive='C:'
        )
        self.assertIn('NÃO PRESERVAR para que não volte automaticamente', text)
        self.assertIn(workflow_texts.withdraw_loss_warning('C:'), text)

    def test_remove_selected_path_choice_calls_withdraw_confirmation_text_and_no_hardcoded_c(self):
        tree = ast.parse(SOURCE)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'remove_selected_path_choice':
                calls = [
                    getattr(n.func, 'id', None)
                    for n in ast.walk(node)
                    if isinstance(n, ast.Call)
                ]
                self.assertIn('withdraw_confirmation_text', calls)
                found = True
        self.assertTrue(found, 'remove_selected_path_choice não encontrado em workflow_ui.py')

        texts_tree = ast.parse(TEXTS_SOURCE)
        for func_name in ('withdraw_choice_hint', 'withdraw_loss_warning', 'withdraw_confirmation_text'):
            for node in ast.walk(texts_tree):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    for child in ast.walk(node):
                        if isinstance(child, ast.Constant) and isinstance(child.value, str):
                            self.assertNotIn('C:', child.value, f'{func_name}: {child.value}')

    def test_runs_without_tkinter(self):
        code = (
            "import sys, unittest; "
            "sys.modules['tkinter'] = None; "
            "sys.modules['tkinter.ttk'] = None; "
            "sys.modules['tkinter.filedialog'] = None; "
            "sys.modules['tkinter.messagebox'] = None; "
            "import tests.test_fix_p4_01_15_withdraw_warning as m; "
            "suite = unittest.TestSuite(["
            "m.WithdrawFromBackupWarningTests('test_hint_next_to_button_warns_about_system_drive_loss'), "
            "m.WithdrawFromBackupWarningTests('test_confirmation_for_system_drive_path_includes_loss_warning'), "
            "m.WithdrawFromBackupWarningTests('test_confirmation_for_non_system_drive_path_omits_loss_warning')"
            "]); "
            "res = unittest.TextTestRunner(verbosity=0).run(suite); "
            "sys.exit(0 if res.wasSuccessful() else 1)"
        )
        proc = subprocess.run(
            [sys.executable, '-c', code],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == '__main__':
    unittest.main()
