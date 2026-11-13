"""FIX-P4-01-09 (R-85): o texto de recusa por conta manda abrir o app normalmente.

Desfazer e Conferir de novo não exigem administrador. Quando a conta é outra (ou
não dá para saber), o caminho que resolve é fechar o app e abri-lo pelo atalho
normal, entrando no Windows com a própria conta. Sem Tk: lê só os textos, a
docstring (por ast) e o manual. Nada é executado.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import test_power_reuse_fix_m3_t3_01 as reuse  # noqa: E402

UI = reuse.UI  # tela carregada com o tkinter falso (sem Tk de verdade)
CHECK = (UI.CHANGES_RECHECK_OTHER_ACCOUNT_TEXT, UI.CHANGES_RECHECK_ACCOUNT_UNKNOWN_TEXT)
UNDO = (UI.CHANGES_OTHER_ACCOUNT_TEXT, UI.CHANGES_ACCOUNT_UNKNOWN_TEXT)


class AccountRefusalTextTests(unittest.TestCase):
    def test_no_text_asks_for_administrator(self):
        for text in CHECK + UNDO:
            self.assertNotIn('botão direito', text)
            self.assertIn('SUA própria conta', text)
            self.assertIn('atalho normal', text)

    def test_nothing_was_done_phrases_kept(self):
        for text in CHECK:
            self.assertIn('Nada foi conferido nem mudado', text)
            self.assertNotIn('desfeito', text)
        for text in UNDO:
            self.assertIn('Nada foi desfeito', text)

    def test_undo_texts_say_machine_wide_tweaks_need_admin(self):
        # O Desfazer tudo não promete aviso em item (o código não avisa): diz na mesma frase
        # qual tipo de ajuste precisa de administrador, igual ao TWEAKS_UNDO_TEXT (R-60, R-86).
        for text in UNDO:
            self.assertNotIn('avisa', text)
            self.assertIn('Os ajustes do computador todo (aba "' + UI.ADVANCED_TAB_LABEL + '")',
                          text)
            self.assertIn('só se desfazem com o app aberto em "Executar como administrador", '
                          'usando a SUA própria conta', text)
            self.assertIn('abra o app pelo atalho normal, na sua própria conta do Windows', text)
        self.assertIn('só se desfazem', UI.TWEAKS_UNDO_TEXT)
        for text in CHECK:  # o Conferir não exige administrador
            self.assertNotIn('administrador', text)
            self.assertNotIn('Executar como administrador', text)
            self.assertIn('abra o app pelo atalho normal, na sua própria conta do Windows', text)

    def test_tweaks_texts_unchanged(self):
        for text in (UI.TWEAKS_OTHER_ACCOUNT_TEXT, UI.TWEAKS_ACCOUNT_UNKNOWN_TEXT):
            self.assertIn('Executar como administrador', text)

    def test_recheck_docstring_says_it_rewrites_the_journal(self):
        tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
        docs = [ast.get_docstring(n) for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == 'recheck_changes']
        self.assertEqual(len(docs), 1)
        self.assertNotIn('Só lê', docs[0])
        self.assertIn('só regrava o diário do app', docs[0])
        self.assertIn('nunca muda o Windows nem desfaz nada', docs[0])

    def test_manual_says_the_same(self):
        manual = ' '.join((ROOT / 'docs' / 'MANUAL.md').read_text(encoding='utf-8').split())
        self.assertIn('conferem a conta antes', manual)
        self.assertIn('Para "Conferir de novo": feche o app e abra de novo pelo atalho normal, '
                      'com a SUA própria conta.', manual)
        self.assertIn('Para "Desfazer tudo": feche o app e abra de novo pelo atalho normal, com '
                      'a SUA própria conta. Os ajustes do computador todo (aba "9 Ajustes '
                      'avançados") só se desfazem com o app aberto em "Executar como '
                      'administrador", usando a SUA própria conta.', manual)
        self.assertNotIn('Abra o app como administrador com a SUA própria conta', manual)

if __name__ == '__main__':
    unittest.main()
