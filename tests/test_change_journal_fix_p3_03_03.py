"""FIX-P3-03-03: ressalvas da revisão da PR #131 (aba "Alterações feitas").

Tudo sintético: TemporaryDirectory, powercfg falso (FakePowercfg da fatia 2a),
ponto de restauração falso e teste de administrador falso. As funções reais
que rodariam powercfg/PowerShell são trocadas por funções que falham se forem
chamadas (SafetyNet da fatia 2a).
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

from tests.test_change_journal_p3_03_fatia2 import (  # noqa: E402
    A, B, C, NO_DISPLAY, _forbidden)
from tests import test_change_journal_p3_03_fatia2b as f2b  # noqa: E402
from tests.test_change_journal_p3_03_fatia2b import NADA, _entry  # noqa: E402

try:
    import optimization_ui as ou
except ImportError:  # Python sem Tk: os testes de tela pulam.
    ou = None


def _buttons(frame):
    found = []
    stack = [frame]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        if widget.winfo_class() in ('TButton', 'Button'):
            found.append(widget)
    return found


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class ChangesReviewFixTests(f2b.ChangesTabHelpers):
    """Reaproveita o painel e os ajudantes da fatia 2b (sem herdar os testes dela)."""

    # ---------- 1. erro inesperado no meio do "Desfazer tudo" ----------
    def test_unexpected_error_after_partial_undo_warns_and_disables_journal(self):
        panel = self.two_changes()
        original = panel.journal._undo_entry  # FIX-M3-T2-02: o que undo_all chama
        state = {'calls': 0}

        def undo(change_id):
            state['calls'] += 1
            if state['calls'] == 1:
                return original(change_id)  # item 2 é desfeito de verdade (no falso)
            raise RuntimeError('C:\\Users\\Fulano\\x')  # item 1: erro cru
        with mock.patch.object(panel.journal, '_undo_entry', side_effect=undo):
            self.undo_all(panel)
        self.assertEqual(self.fake.current, B)  # parte já mudou no "sistema"
        expected = ou.CHANGES_UNEXPECTED_ERROR_TEXT
        self.assertIn('Algumas alterações podem já ter sido desfeitas', expected)
        self.assertIn('fechar e abrir o app de novo', expected)
        self.assertEqual(panel.changes_status.get(), expected)
        # FIX-P3-03-04 (R-28): uma janela só, com o título "Desfazer tudo".
        # FIX-P3-03-05: a janela mostra só o texto completo (sem POWER_JOURNAL_OFF_TEXT).
        self.assertEqual(self.messages, [('error', 'Desfazer tudo', expected)])
        msg = self.messages[0][2]
        self.assertNotIn(ou.POWER_JOURNAL_OFF_TEXT, msg)
        self.assertNotIn('trocas de plano', msg)
        self.assertIn(ou.CHANGES_TAB_LABEL, expected)
        self.assertEqual(msg.count('desligad'), 1)
        # FIX-P3-03-04: sem "Por segurança" e sem o tipo de ajuste fixo no texto.
        self.assertNotIn('Por segurança', msg)
        self.assertNotIn('plano de energia', msg)
        self.assertEqual(panel.journal_error, expected)
        shown = ' '.join(m[2] for m in self.messages)
        for text in (shown, panel.changes_status.get(), panel.power_status.get(),
                     panel.journal_error, self.changes(panel)):
            self.assertNotIn(NADA, text)
            self.assertNotIn('Fulano', text)
        for button in (panel.btn_apply, panel.btn_revert, panel.btn_undo_all):
            self.assertTrue(button.instate(['disabled']))

    # ---------- 2. aviso de "desconhecido" não esconde o resultado ----------
    def test_unknown_keeps_power_status_result_visible(self):
        self.write_journal(_entry(1, 'applied', A, B), _entry(2, 'unknown', B, C))
        self.fake.current = B
        panel = self.panel()
        self.root.update()
        expected = ou.CHANGES_UNKNOWN_TEXT.format(n=1)
        self.assertEqual(panel.power_block.get(), expected)
        self.assertNotEqual(panel.power_status.get(), expected)
        self.answer['value'] = True
        panel.btn_revert.invoke()
        self.wait_idle(panel)
        self.assertEqual(self.fake.current, A)
        self.assertEqual(panel.power_status.get(), 'Plano de energia anterior restaurado.')
        self.assertIn(expected, panel.power_block.get())
        # Sem item desconhecido, o rótulo de bloqueio fica vazio.
        self.journal_file.unlink()
        panel2 = self.panel()
        self.root.update()
        self.assertEqual(panel2.power_block.get(), '')

    # ---------- 3. aba 7 diz onde fica o botão da troca antiga ----------
    def test_changes_tab_legacy_applied_says_where_button_is(self):
        raw = json.dumps({'schema': 'pcro-power-1', 'status': 'applied',
                          'previous': A, 'requested': B}).encode('utf-8')
        self.legacy_file().write_bytes(raw)
        self.fake.current = B
        with mock.patch.object(ou, 'revert_power_plan', side_effect=_forbidden):
            panel = self.panel()
            self.root.update()
        names = [panel.tabs.tab(t, 'text') for t in panel.tabs.tabs()]
        self.assertIn('4  Energia reversível', names)
        self.assertIn('"4  Energia reversível"', ou.CHANGES_LEGACY_WHERE_TEXT)
        text = self.changes(panel)
        self.assertIn(ou.POWER_LEGACY_TEXT + ' ' + ou.CHANGES_LEGACY_WHERE_TEXT, text)
        # P3-03 fatia 2b-2: a aba 7 ganhou o "Conferir de novo" (só lê).
        self.assertCountEqual(_buttons(panel.changes_frame), [panel.btn_undo_all, panel.btn_recheck])
        self.assertNotIn(panel.btn_legacy, _buttons(panel.changes_frame))
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.legacy_file().read_bytes(), raw)

    # ---------- 4. singular e plural ----------
    def test_undo_all_single_item_uses_singular(self):
        panel = self.panel()
        self.apply(panel, B)
        self.undo_all(panel)
        self.assertEqual(self.fake.current, A)
        self.assertEqual(ou.CHANGES_ONE_UNDONE_TEXT, 'A alteração foi desfeita.')
        self.assertEqual(panel.changes_status.get(), ou.CHANGES_ONE_UNDONE_TEXT)
        self.assertEqual(panel.note.get(), ou.CHANGES_ONE_UNDONE_TEXT)

    def test_undo_all_two_items_keeps_plural(self):
        panel = self.two_changes()
        self.undo_all(panel)
        self.assertEqual(self.fake.current, A)
        self.assertEqual(panel.changes_status.get(), 'Todas as 2 alterações foram desfeitas.')


class HelpersHaveNoTestsTests(unittest.TestCase):
    """FIX-P3-03-04: a base de ajudantes não pode trazer testes (senão rodam duas vezes)."""

    def test_helpers_base_has_no_tests(self):
        self.assertEqual([n for n in dir(f2b.ChangesTabHelpers) if n.startswith('test_')], [])
        self.assertFalse(issubclass(ChangesReviewFixTests, f2b.ChangesTabTests))


if __name__ == '__main__':
    unittest.main()
