"""FIX-P4-01-10: os textos do workflow não citam letras fixas (D:, F:, G:).

Lê o workflow_ui.py com `ast`, sem abrir janela (não precisa do Tk). Nada é apagado.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'workflow_ui.py').read_text(encoding='utf-8')
FUNCS = ('build_overview', 'build_preservation', 'build_installation')
NEW_TEXTS = (
    'Escolha o que manter em cada unidade. Prepare o C: antes de reinstalar o Windows: '
    'o que não for copiado dele não entra no backup. Os outros discos e unidades ficam '
    'como estão: nada é apagado.',
    'C: exige cópia verificada antes de reinstalar. Os outros discos e unidades ficam como estão. '
    'Nada é apagado, nem os itens pendentes.',
    'Revisar dados do C: associados a jogos instalados em outros discos ou unidades, '
    'que continuam onde estão.',
)
OLD_TEXTS = ('permanecem intactos', 'podem ficar intactos', 'permanecerão em D:')


def _strings_of(func_name):
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return [n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    raise AssertionError(f'{func_name} não encontrado em workflow_ui.py')


class WorkflowTextTests(unittest.TestCase):
    def test_no_fixed_letters(self):
        for func in FUNCS:
            for text in _strings_of(func):
                if len(text) > 3:
                    for letter in ('D:', 'F:', 'G:'):
                        self.assertNotIn(letter, text, func)

    def test_new_texts_present(self):
        every = [t for f in FUNCS for t in _strings_of(f)]
        for text in NEW_TEXTS:
            self.assertIn(text, every)

    def test_old_texts_gone(self):
        for old in OLD_TEXTS:
            self.assertNotIn(old, SOURCE)


if __name__ == '__main__':
    unittest.main()
