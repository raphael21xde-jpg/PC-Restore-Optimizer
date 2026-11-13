"""FIX-P4-01-11: a revisão do backup lembra que o que não for marcado no C: fica fora do backup.

A frase diz que o que não for marcado no C: não entra no backup e se perde quando o
instalador formatar o C:, e que o app não apaga nenhum arquivo dos outros discos (R-88).
Nenhuma string de `_build_review` cita D:, F: ou G:.

Lê o app.py com `ast`, sem abrir janela (não precisa do Tk). Nada é apagado.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app.py').read_text(encoding='utf-8')
NEW_TEXT = ('Somente os arquivos marcados no C: serão copiados. O que não for marcado no C: '
            'não entra no backup e se perde quando o instalador formatar o C:. '
            'O app não apaga nenhum arquivo dos outros discos e unidades.')
REQUIRED = ('não entra no backup', 'se perde quando o instalador formatar o C:',
            'não apaga nenhum arquivo')
OLD_TEXTS = ('ficam como estão: nada é apagado', 'nada é apagado.',
             'não mexe', 'só grava')


def _strings_of(func_name):
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return [n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    raise AssertionError(f'{func_name} não encontrado em app.py')


class ReviewBackupTextTests(unittest.TestCase):
    def test_new_text_present(self):
        self.assertIn(NEW_TEXT, _strings_of('_build_review'))

    def test_new_text_has_loss_warning_and_no_delete(self):
        for part in REQUIRED:
            self.assertIn(part, NEW_TEXT)

    def test_old_texts_gone(self):
        for text in _strings_of('_build_review'):
            for old in OLD_TEXTS:
                self.assertNotIn(old, text)
        self.assertNotIn('ficam como estão: nada é apagado', SOURCE)

    def test_no_fixed_letters(self):
        for text in _strings_of('_build_review'):
            for letter in ('D:', 'F:', 'G:'):
                self.assertNotIn(letter, text)


if __name__ == '__main__':
    unittest.main()
