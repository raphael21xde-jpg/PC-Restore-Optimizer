"""FIX-P4-01-01: o texto de administrador e a docstring do "Desfazer tudo" não dizem mais
que todo desfazer funciona sem administrador (os ajustes do computador todo, aba 9, precisam).

FIX-P4-01-07 (R-79): o resumo do desfazer, na tela, na docstring e no manual, diz também a
exceção da R-69 (valor apagado fora do app = item pulado).

Carrega optimization_ui com o tkinter falso do FIX-M3-T3-01 (não abre janela) e lê o
manual como texto."""
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from test_power_reuse_fix_m3_t3_01 import UI  # noqa: E402

MANUAL = ROOT / 'docs' / 'MANUAL.md'
EXCEPTION_PIECES = ('apagado fora do app', 'pulado', 'mais antigos')


def _load():
    consts = {name: getattr(UI, name) for name in
              ('ADVANCED_TAB_LABEL', 'TWEAKS_ADMIN_TEXT', 'TWEAKS_ADMIN_APPLY_TEXT', 'TWEAKS_UNDO_TEXT')}
    return consts, inspect.getdoc(UI.OptimizationPanel.undo_all_changes)


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
        # FIX-P4-01-07: o desfazer é um parágrafo separado (linha em branco antes)
        self.assertIn('do jeito normal.\n\nDesfazer os ajustes', self.text)
        self.assertEqual(self.text, self.consts['TWEAKS_ADMIN_APPLY_TEXT'] + '\n\n'
                         + self.consts['TWEAKS_UNDO_TEXT'])
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

    # ---------- FIX-P4-01-07 (R-79): a exceção da R-69 nos três lugares ----------
    def test_screen_text_states_skip_exception(self):
        undo = self.consts['TWEAKS_UNDO_TEXT']
        for piece in EXCEPTION_PIECES:
            self.assertIn(piece, undo)
        self.assertIn('Exceção: um ajuste cujo valor foi apagado fora do app', undo)
        self.assertIn('continua na lista, e o desfazer segue para os mais antigos', undo)
        # a exceção vem depois da regra geral de parar
        self.assertLess(undo.index('para nesse ajuste'), undo.index('apagado fora do app'))

    def test_docstring_states_skip_exception_and_account(self):
        doc = ' '.join(self.doc.split())
        for piece in EXCEPTION_PIECES + ('R-69', 'R-55', 'conta', 'nada é desfeito'):
            self.assertIn(piece, doc)

    def test_manual_states_same_exception(self):
        manual = ' '.join(MANUAL.read_text(encoding='utf-8').split())
        self.assertIn('um ajuste cujo valor foi apagado fora do app', manual)
        self.assertIn('é pulado: ele continua na lista, e o desfazer segue para os mais antigos',
                      manual)


if __name__ == '__main__':
    unittest.main()
