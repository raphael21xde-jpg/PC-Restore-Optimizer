"""FIX-P4-01-08: o "Conferir de novo" confere a conta do Windows antes de ler (R-55).

Se o app estiver aberto com outra conta, ou não der para saber a conta, nada é
conferido nem mudado: o diário não é lido de novo nem regravado, e os planos e
ajustes não são relidos. A conta é conferida dentro do Job, nunca na thread da
tela (R-56). Os textos do "Desfazer tudo" e o manual dizem a recusa por conta (R-72).

Roda sem Tk, com o mesmo painel montado do FIX-P4-01-04. Diário sintético em
TemporaryDirectory, plano de energia falso, conta simulada (probe injetado).
Nenhum comando real.
"""
import ast
import json
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import change_journal as cj  # noqa: E402
import session_owner as so  # noqa: E402
import test_fix_p4_01_04_undo_account as undo  # noqa: E402

UI = undo.UI
GUID = undo.GUID
OTHER_GUID = undo.OTHER_GUID


class RecheckAccountHelpers(undo.UndoAccountHelpers):
    def setUp(self):
        super().setUp()
        self.rechecks = []

    def panel(self):
        panel = super().panel()
        original = panel.journal.recheck

        def recording():
            self.rechecks.append(1)
            return original()
        panel.journal.recheck = recording
        return panel


class RecheckAccountFlowTests(RecheckAccountHelpers):
    def assert_refused(self, panel, text):
        before = self.path.read_bytes()
        panel.recheck_changes()
        self.assertEqual(self.rechecks, [])
        self.assertEqual(self.path.read_bytes(), before)  # diário igual, byte a byte
        self.assertEqual(self.statuses(panel), ['applied'])
        self.assertEqual(self.power.reads, 1)  # só o panel() de teste leu os planos
        self.assertEqual(self.tweak_reads, [])
        self.assertEqual(self.power.reverts, [])
        self.assertEqual(panel.changes_status.get(), text)
        self.assertIn(('warning', UI.CHANGES_RECHECK_TITLE, text), self.shown)
        self.assertIn('Nada foi conferido nem mudado', text)
        self.assertIn('SUA própria conta', text)
        self.assertIn('Executar como administrador', text)
        self.assertNotIn('desfeito', text)

    def test_other_account_checks_nothing(self):
        self.owner = so.OTHER
        self.power.current = GUID  # o recheck acertaria o diário se rodasse
        panel = self.panel()
        self.assert_refused(panel, UI.CHANGES_RECHECK_OTHER_ACCOUNT_TEXT)
        self.assertIn('outra conta', UI.CHANGES_RECHECK_OTHER_ACCOUNT_TEXT)
        self.assertEqual(self.owner_threads, [True])  # o Job falso roda na hora

    def test_unknown_account_checks_nothing(self):
        self.owner = so.UNKNOWN
        self.power.current = GUID
        panel = self.panel()
        self.assert_refused(panel, UI.CHANGES_RECHECK_ACCOUNT_UNKNOWN_TEXT)
        self.assertIn('Não deu para confirmar', UI.CHANGES_RECHECK_ACCOUNT_UNKNOWN_TEXT)

    def test_probe_error_counts_as_unknown(self):
        def broken():
            raise OSError('sem resposta')
        self.power.current = GUID
        panel = self.panel()
        panel._session_owner_probe = broken
        self.assert_refused(panel, UI.CHANGES_RECHECK_ACCOUNT_UNKNOWN_TEXT)

    def test_same_account_rechecks_as_before(self):
        self.power.current = GUID  # o plano voltou por fora: o diário vira "reverted"
        panel = self.panel()
        panel.recheck_changes()
        self.assertEqual(self.rechecks, [1])
        self.assertEqual(self.statuses(panel), ['reverted'])
        on_disk = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual([e['status'] for e in on_disk['entries']], ['reverted'])
        self.assertEqual(self.power.reverts, [])  # conferir nunca desfaz
        self.assertEqual(self.tweak_reads, [1])
        self.assertEqual(panel.changes_status.get(), UI.CHANGES_RECHECK_FIXED_TEXT.format(n=1))
        self.assertFalse([s for s in self.shown if s[0] == 'warning'])
        self.assertEqual(self.asked, [])  # sem pergunta Sim/Não


class SlowProbeTests(RecheckAccountHelpers):
    def test_slow_probe_does_not_block_screen(self):
        release = threading.Event()
        jobs = []

        def slow():
            self.owner_threads.append(threading.current_thread() is threading.main_thread())
            release.wait(5)
            return so.SAME

        def thread_job(work, done):
            box = {}
            thread = threading.Thread(target=lambda: box.update(value=work()), daemon=True)
            thread.start()
            jobs.append((thread, box, done))

        self.power.current = GUID
        panel = self.panel()
        panel._session_owner_probe = slow
        panel._run_power_job = thread_job
        started = time.monotonic()
        panel.recheck_changes()
        self.assertLess(time.monotonic() - started, 1.0)  # a tela não esperou a conta
        self.assertEqual(self.rechecks, [])
        release.set()
        thread, box, done = jobs[0]
        thread.join(5)
        self.assertFalse(thread.is_alive())
        done(box['value'])
        self.assertEqual(self.owner_threads, [False])
        self.assertEqual(self.rechecks, [1])
        self.assertEqual(self.statuses(panel), ['reverted'])


class SourceTests(unittest.TestCase):
    def test_account_checked_inside_job_before_recheck(self):
        start = undo._function('recheck_changes')
        works = [n for n in start.body if isinstance(n, ast.FunctionDef) and n.name == 'work']
        self.assertEqual(len(works), 1)
        work = ast.unparse(works[0])
        self.assertIn('session_owner.session_owner(self._session_owner_probe)', work)
        self.assertLess(work.index('session_owner.session_owner'), work.index('recheck()'))
        self.assertLess(work.index('session_owner.session_owner'), work.index('_read_plans_work'))
        # Fora do work (thread da tela) não há consulta da conta (R-56).
        outside = ast.unparse(ast.Module(body=[n for n in start.body if n is not works[0]],
                                         type_ignores=[]))
        self.assertNotIn('session_owner.session_owner', outside)
        self.assertNotIn('session_owner.session_owner', ast.unparse(undo._function('_recheck_done')))

    def test_done_handles_account_before_rereading(self):
        code = ast.unparse(undo._function('_recheck_done'))
        self.assertIn("'account'", code)
        self.assertLess(code.index("'account'"), code.index('self._after_power_job'))

    def test_docstring_mentions_account(self):
        doc = ast.get_docstring(undo._function('recheck_changes'))
        self.assertIn('conta', doc)


class UndoTextsTests(unittest.TestCase):
    def test_confirm_text_states_account_refusal(self):
        self.assertIn('outra conta', UI.CHANGES_CONFIRM_TEXT)
        self.assertIn('não desfaz nada', UI.CHANGES_CONFIRM_TEXT)
        UI.CHANGES_CONFIRM_TEXT.format(n=2)  # o {n} continua funcionando

    def test_tweaks_undo_text_states_account_refusal(self):
        self.assertIn('outra conta', UI.TWEAKS_UNDO_TEXT)
        self.assertIn('não desfaz nada', UI.TWEAKS_UNDO_TEXT)

    def test_manual_states_account_refusal(self):
        manual = (ROOT / 'docs' / 'MANUAL.md').read_text(encoding='utf-8')
        self.assertIn('outra conta', manual)
        self.assertIn('"Conferir de novo" conferem a conta', manual)


if __name__ == '__main__':
    unittest.main()
