"""FIX-P3-03-05: ressalvas da revisão da PR #135 (texto do erro inesperado e aba 7).

Tudo sintético: reaproveita o painel e os ajudantes da fatia 2b (TemporaryDirectory,
powercfg falso, ponto de restauração falso). Nenhum comando real é executado.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from tests.test_change_journal_p3_03_fatia2 import C, NO_DISPLAY  # noqa: E402
from tests import test_change_journal_p3_03_fatia2b as f2b  # noqa: E402
import change_journal as cj  # noqa: E402

try:
    import optimization_ui as ou
except ImportError:  # Python sem Tk: os testes de tela pulam.
    ou = None


@unittest.skipIf(ou is None, 'Sem Tk')
class UnexpectedErrorTextTests(unittest.TestCase):
    def test_text_points_to_changes_tab_and_says_off_once(self):
        text = ou.CHANGES_UNEXPECTED_ERROR_TEXT
        self.assertEqual(ou.CHANGES_TAB_LABEL, '7  Alterações feitas')
        self.assertIn('"' + ou.CHANGES_TAB_LABEL + '"', text)
        self.assertIn('Algumas alterações podem já ter sido desfeitas', text)
        self.assertIn('fechar e abrir o app de novo', text)
        self.assertEqual(text.count('desligad'), 1)
        for absent in ('trocas de plano', 'plano de energia', 'Por segurança',
                       'Configurações do Windows'):
            self.assertNotIn(absent, text)


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class ChangesTabLabelAndOtherErrorsTests(f2b.ChangesTabHelpers):
    def test_seventh_tab_label_is_the_constant(self):
        panel = self.panel()
        self.root.update()
        tabs = panel.tabs.tabs()
        # P3-04 e P3-05: as abas 8 e 9 vieram depois; a 7 continua sendo "Alterações feitas".
        self.assertEqual(len(tabs), 9)
        self.assertEqual(panel.tabs.tab(tabs[6], 'text'), ou.CHANGES_TAB_LABEL)

    def test_other_journal_error_still_ends_with_off_text(self):
        panel = self.two_changes()
        self.journal_file.write_bytes(b'{"outra": "janela"}')
        self.undo_all(panel)
        self.assertEqual(self.fake.current, C)
        self.assertEqual(len(self.messages), 1)
        kind, title, text = self.messages[0]
        self.assertEqual((kind, title), ('error', 'Diário de alterações'))
        self.assertEqual(text, cj.MSG_OTHER_WINDOW + ' ' + ou.POWER_JOURNAL_OFF_TEXT)
        self.assertTrue(text.endswith(ou.POWER_JOURNAL_OFF_TEXT))

    def test_unexpected_error_opens_one_window_with_full_text(self):
        panel = self.two_changes()
        with mock.patch.object(panel.journal, 'undo_all', side_effect=RuntimeError('x')):
            self.undo_all(panel)
        self.assertEqual(self.messages,
                         [('error', 'Desfazer tudo', ou.CHANGES_UNEXPECTED_ERROR_TEXT)])


if __name__ == '__main__':
    unittest.main()
