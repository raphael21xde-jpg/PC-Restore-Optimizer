"""FIX-P4-01-06: a tela de revisão do backup não cita letras fixas (D:, F:, G:).

Lê o app.py com `ast`, sem abrir janela (não precisa do Tk). Nada é apagado.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Frase atualizada no FIX-P4-01-11 (R-03).
NEW_TEXT = ('Somente os arquivos marcados no C: serão copiados. O que não for marcado no C: '
            'não entra no backup e se perde quando o instalador formatar o C:. '
            'O app não apaga nenhum arquivo dos outros discos e unidades.')


def _strings_of(func_name):
    tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return [n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    raise AssertionError(f'{func_name} não encontrado em app.py')


class ReviewTextTests(unittest.TestCase):
    def test_no_fixed_letters(self):
        for text in _strings_of('_build_review'):
            for letter in ('D:', 'F:', 'G:'):
                self.assertNotIn(letter, text)

    def test_new_text_present(self):
        self.assertIn(NEW_TEXT, _strings_of('_build_review'))


if __name__ == '__main__':
    unittest.main()
