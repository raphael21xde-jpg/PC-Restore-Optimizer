"""FIX-P3-03-06: ressalvas da revisão da PR #137 (issue #138).

- depois do erro inesperado do "Desfazer tudo", a linha de status da aba 4 e a aba 7 falam
  em "desligado" uma vez só, sem "trocas de plano"; a caixa de texto da aba 4 não é
  redesenhada e continua com a lista de planos (FIX-P3-03-07);
- o botão "Desfazer alteração antiga" também fica desligado com o diário desligado (R-30);
- o texto do erro inesperado fala em "botões de aplicar e desfazer ajustes";
- FIX-P3-03-07 (issue #143): diário ausente também desliga "Desfazer alteração antiga" e
  recarregar o diário volta a frase padrão de "desligado".

Tudo sintético: reaproveita o painel e os ajudantes da fatia 2b (TemporaryDirectory,
powercfg falso, ponto de restauração falso). Nenhum comando real é executado.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from tests.test_change_journal_p3_03_fatia2 import A, B, C, NO_DISPLAY, _forbidden  # noqa: E402
from tests import test_change_journal_p3_03_fatia2b as f2b  # noqa: E402
import change_journal as cj  # noqa: E402

try:
    import optimization_ui as ou
except ImportError:  # Python sem Tk: os testes de tela pulam.
    ou = None

LEGACY_APPLIED = json.dumps({'schema': 'pcro-power-1', 'status': 'applied',
                             'previous': A, 'requested': B}).encode('utf-8')


@unittest.skipIf(ou is None, 'Sem Tk')
class UnexpectedErrorWordingTests(unittest.TestCase):
    def test_text_names_apply_and_undo_buttons(self):
        text = ou.CHANGES_UNEXPECTED_ERROR_TEXT
        self.assertIn('aplicar e desfazer ajustes', text)
        self.assertNotIn('botões de troca', text)
        self.assertEqual(text.count('desligad'), 1)
        self.assertNotIn(f2b.NADA, text)


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class JournalOffTextTests(f2b.ChangesTabHelpers):
    def power_text(self, panel):
        return panel.power_text.get('1.0', 'end')

    def unexpected_error(self, panel):
        with mock.patch.object(panel.journal, 'undo_all', side_effect=RuntimeError('x')):
            self.undo_all(panel)  # espera o Job terminar (R-06)

    def test_unexpected_error_says_off_once_everywhere(self):
        panel = self.two_changes()
        before = self.power_text(panel)
        self.unexpected_error(panel)
        status = panel.power_status.get()
        self.assertEqual(status, ou.CHANGES_UNEXPECTED_ERROR_TEXT)
        for text in (status, self.changes(panel), panel.changes_status.get()):
            with self.subTest(text=text[:40]):
                self.assertEqual(text.count('desligad'), 1)
                self.assertNotIn('trocas de plano', text)
                self.assertNotIn(f2b.NADA, text)
        # FIX-P3-03-07 (R-31): a caixa de texto da aba 4 não é redesenhada com o erro;
        # ela mostra a lista de planos lida de novo pelo Job, sem "desligado".
        intro = self.power_text(panel)
        self.assertTrue(intro.startswith('PLANOS DO WINDOWS — LEITURA\n'))
        self.assertEqual(intro, before)
        self.assertNotIn('desligad', intro)
        self.assertNotIn('trocas de plano', intro)
        self.assertNotIn(ou.POWER_JOURNAL_OFF_TEXT, intro)
        self.assertTrue(panel.btn_apply.instate(['disabled']))
        self.assertTrue(panel.btn_revert.instate(['disabled']))
        self.assertTrue(panel.btn_undo_all.instate(['disabled']))

    def test_intro_after_unreadable_journal_still_has_off_text(self):
        self.journal_file.write_bytes(b'{nao e json')
        panel = self.panel()
        self.root.update()
        intro = self.power_text(panel)
        self.assertIn(ou.POWER_JOURNAL_OFF_TEXT, intro)
        self.assertEqual(intro.count('desligad'), 1)
        self.assertTrue(panel.power_status.get().endswith(ou.POWER_JOURNAL_OFF_TEXT))
        self.assertEqual(self.fake.calls, [])

    def test_legacy_button_disabled_after_unexpected_error(self):
        self.write_journal(f2b._entry(1, 'applied', A, C))
        self.legacy_file().write_bytes(LEGACY_APPLIED)
        self.fake.current = C
        panel = self.panel()
        self.root.update()
        self.assertTrue(panel.btn_legacy.winfo_manager())
        self.assertTrue(panel.btn_legacy.instate(['!disabled']))
        self.unexpected_error(panel)
        self.root.update()
        self.assertTrue(panel.btn_legacy.instate(['disabled']))
        self.fake.calls.clear()
        self.messages.clear()
        self.answers.clear()
        with mock.patch.object(ou, 'revert_power_plan', side_effect=_forbidden) as old:
            panel.undo_legacy_plan()
            self.wait_idle(panel)
        old.assert_not_called()
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.answers, [])
        self.assertEqual(self.legacy_file().read_bytes(), LEGACY_APPLIED)
        self.assertEqual(len(self.messages), 1)
        kind, title, text = self.messages[0]
        self.assertEqual((kind, title), ('error', 'Desfazer alteração antiga'))
        self.assertEqual(text, ou.CHANGES_UNEXPECTED_ERROR_TEXT)
        self.assertEqual(self.fake.current, C)

    def test_other_journal_error_keeps_off_text_and_disables_legacy(self):
        self.write_journal(f2b._entry(1, 'applied', A, C))
        self.legacy_file().write_bytes(LEGACY_APPLIED)
        self.fake.current = C
        panel = self.panel()
        self.root.update()
        self.journal_file.write_bytes(b'{"outra": "janela"}')
        self.undo_all(panel)
        self.root.update()
        expected = cj.MSG_OTHER_WINDOW + ' ' + ou.POWER_JOURNAL_OFF_TEXT
        self.assertEqual(panel.power_status.get(), expected)
        self.assertTrue(self.changes(panel).rstrip('\n').split('\n')[1]
                        .endswith(ou.POWER_JOURNAL_OFF_TEXT))
        self.assertTrue(panel.btn_legacy.instate(['disabled']))
        self.messages.clear()
        with mock.patch.object(ou, 'revert_power_plan', side_effect=_forbidden) as old:
            panel.undo_legacy_plan()
            self.wait_idle(panel)
        old.assert_not_called()
        self.assertEqual(self.messages,
                         [('error', 'Desfazer alteração antiga', expected)])
        self.assertEqual(self.legacy_file().read_bytes(), LEGACY_APPLIED)


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class FixP30307Tests(f2b.ChangesTabHelpers):
    """FIX-P3-03-07 (issue #143): ressalvas da revisão da PR #142."""
    unexpected_error = JournalOffTextTests.unexpected_error

    def test_legacy_refuses_when_journal_is_none(self):
        """Defesa dupla de `undo_legacy_plan` (FIX-P3-03-08, issue #147).

        O estado `journal=None` + `journal_error=''` é montado à mão: hoje o app não chega
        nele. O `__init__` do painel começa assim, mas chama `_load_change_journal` logo em
        seguida, antes de montar a tela; esse método deixa um diário válido ou `journal=None`
        com `journal_error=str(exc)`, e todo `JournalError` de `change_journal.py` tem texto
        fixo, nunca vazio. `_journal_failed` recebe o texto de um `JournalError`, um texto
        fixo do app (`CHANGES_UNEXPECTED_ERROR_TEXT`, `CHANGES_RECHECK_ERROR_TEXT`) ou, no
        "Desfazer tudo" parcial, `CHANGES_DONE_BEFORE_ERROR_TEXT` seguido do texto do erro
        (também nunca vazio, porque começa com o texto fixo).
        O teste fica porque `undo_legacy_plan` e `_update_power_buttons` testam
        `journal is None or journal_error`: se um dia surgir um erro sem texto, o botão
        antigo continua desligado e nada roda.
        """
        self.write_journal(f2b._entry(1, 'applied', A, C))
        self.legacy_file().write_bytes(LEGACY_APPLIED)
        self.fake.current = C
        panel = self.panel()
        self.root.update()
        panel.journal = None
        panel.journal_error = ''
        panel._update_power_buttons()
        self.assertTrue(panel.btn_legacy.instate(['disabled']))
        self.fake.calls.clear()
        self.messages.clear()
        self.answers.clear()
        expected = 'O diário de alterações não está disponível. ' + ou.POWER_JOURNAL_OFF_TEXT
        with mock.patch.object(ou, 'revert_power_plan', side_effect=_forbidden) as old:
            panel.undo_legacy_plan()
            self.wait_idle(panel)
        old.assert_not_called()
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.answers, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.legacy_file().read_bytes(), LEGACY_APPLIED)
        self.assertEqual(self.messages, [('error', 'Desfazer alteração antiga', expected)])
        self.assertEqual(self.fake.current, C)

    def test_reload_restores_default_off_text(self):
        panel = self.two_changes()
        self.unexpected_error(panel)
        self.assertIsNone(panel.journal_off_text)
        self.journal_file.write_bytes(b'{nao e json')
        panel._load_change_journal()
        self.assertEqual(panel.journal_off_text, ou.POWER_JOURNAL_OFF_TEXT)
        self.assertIsNone(panel.journal)
        self.assertEqual(panel._journal_error_text(),
                         panel.journal_error + ' ' + ou.POWER_JOURNAL_OFF_TEXT)

    def test_reload_ok_clears_error_and_restores_off_text(self):
        panel = self.two_changes()
        self.unexpected_error(panel)
        panel._load_change_journal()
        self.assertEqual(panel.journal_error, '')
        self.assertIsNotNone(panel.journal)
        self.assertEqual(panel.journal_off_text, ou.POWER_JOURNAL_OFF_TEXT)


if __name__ == '__main__':
    unittest.main()
