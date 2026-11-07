"""FIX-P4-01-01: o texto de administrador e a docstring do "Desfazer tudo" não dizem mais
que todo desfazer funciona sem administrador (os ajustes do computador todo, aba 9, precisam).

Lê optimization_ui.py com ast, sem importar Tk."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / 'optimization_ui.py'


def _load():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    consts = {}
    docstring = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('ADVANCED_TAB_LABEL', 'TWEAKS_ADMIN_TEXT'):
                expr = ast.Expression(node.value)
                ast.fix_missing_locations(expr)
                consts[name] = eval(compile(expr, str(SOURCE), 'eval'), {}, dict(consts))
        if isinstance(node, ast.ClassDef) and node.name == 'OptimizationPanel':
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == 'undo_all_changes':
                    docstring = ast.get_docstring(item)
    return consts, docstring


class UndoAdminTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.consts, cls.doc = _load()
        cls.text = cls.consts['TWEAKS_ADMIN_TEXT']

    def test_old_sentence_removed(self):
        self.assertNotIn('Desfazer funciona sem administrador.', self.text)

    def test_new_sentence_explains_scopes(self):
        for piece in ('sua conta', 'sem administrador', 'computador todo', 'administrador',
                      'reiniciar', 'para nesse ajuste', self.consts['ADVANCED_TAB_LABEL']):
            self.assertIn(piece, self.text)
        # espaço certo entre a frase anterior e a nova
        self.assertIn('do jeito normal. Desfazer os ajustes', self.text)
        # o nome da aba tem dois espaços de propósito; fora dele, nenhum espaço duplo
        self.assertNotIn('  ', self.text.replace(self.consts['ADVANCED_TAB_LABEL'], ''))

    def test_previous_account_warnings_kept(self):
        for piece in ('OUTRA conta', 'SUA própria conta', 'confere a conta'):
            self.assertIn(piece, self.text)

    def test_undo_all_docstring(self):
        self.assertIsNotNone(self.doc)
        self.assertNotIn('Não exige administrador', self.doc)
        for piece in ('administrador', 'reiniciar', 'primeiro item que falha'):
            self.assertIn(piece, self.doc)


if __name__ == '__main__':
    unittest.main()
