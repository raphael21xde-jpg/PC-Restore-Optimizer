"""FIX-P4-01-15: "Retirar do backup" e "NÃO será apagado" avisam que o item do C: se perde na formatação (R-88).

1. Ao lado do botão "Retirar do backup (não apaga)" (`workflow_ui.py`, ~linha 150), o texto
   `WITHDRAW_CHOICE_HINT` lembra que, no C:, o item fica fora do backup e se perde quando o
   instalador formatar o C:.
2. Na confirmação ao retirar (`withdraw_confirmation_text`, ~linha 300), após
   "O arquivo original NÃO será apagado.", acrescenta a frase de perda na formatação
   **somente** para caminhos no C: (caminhos em D: ou outras unidades não trazem essa frase).

Sem Tk e sem tocar em discos reais.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

import workflow_ui

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'workflow_ui.py').read_text(encoding='utf-8')


class WithdrawFromBackupWarningTests(unittest.TestCase):
    def test_hint_next_to_button_warns_about_c_loss(self):
        self.assertIn('fica fora do backup', workflow_ui.WITHDRAW_CHOICE_HINT)
        self.assertIn('se perde quando o instalador formatar o C:', workflow_ui.WITHDRAW_CHOICE_HINT)
        self.assertNotIn(
            "'Selecione um caminho acima para retirar somente sua marcação.'",
            SOURCE,
        )
        self.assertIn('text=WITHDRAW_CHOICE_HINT', SOURCE)
        self.assertIn("text='Retirar do backup (não apaga)'", SOURCE)

    def test_confirmation_for_c_path_includes_c_loss_warning(self):
        for c_path in (r'C:\Users\Teste\Documentos', 'c:/jogos/save'):
            text = workflow_ui.withdraw_confirmation_text(c_path, linked=False)
            self.assertIn('O arquivo original NÃO será apagado.', text)
            self.assertIn(workflow_ui.WITHDRAW_C_LOSS_WARNING, text)
            self.assertIn('fica fora do backup', text)
            self.assertIn('se perde quando o instalador formatar o C:', text)
            self.assertIn('Nenhuma cópia, limpeza ou formatação será realizada.', text)

    def test_confirmation_for_non_c_path_omits_c_loss_warning(self):
        for other_path in (r'D:\SteamLibrary\Game', 'E:/Arquivos'):
            text = workflow_ui.withdraw_confirmation_text(other_path, linked=False)
            self.assertIn('O arquivo original NÃO será apagado.', text)
            self.assertNotIn(workflow_ui.WITHDRAW_C_LOSS_WARNING, text)
            self.assertNotIn('formatar o C:', text)
            self.assertIn('Nenhuma cópia, limpeza ou formatação será realizada.', text)

    def test_confirmation_preserves_linked_game_save_notice(self):
        text = workflow_ui.withdraw_confirmation_text(r'C:\Users\Teste\Save', linked=True)
        self.assertIn('NÃO PRESERVAR para que não volte automaticamente', text)
        self.assertIn(workflow_ui.WITHDRAW_C_LOSS_WARNING, text)

    def test_remove_selected_path_choice_calls_withdraw_confirmation_text(self):
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


if __name__ == '__main__':
    unittest.main()
