"""FIX-P4-01-04: o "Desfazer tudo" confere a conta do Windows antes de desfazer (R-55).

Se o app estiver aberto com outra conta, ou não der para saber a conta, nada é
desfeito e nada é relido. A conta é conferida dentro do Job, nunca na thread da
tela (R-56).

Roda sem Tk: a tela é carregada com o ``tkinter`` falso do FIX-M3-T3-01 e o painel
é montado só com os campos que o fluxo usa. Diário sintético em TemporaryDirectory,
plano de energia falso, conta simulada (probe injetado). Nenhum comando real.
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
import optimization_engine as oe  # noqa: E402
import session_owner as so  # noqa: E402
import test_power_reuse_fix_m3_t3_01 as reuse  # noqa: E402

UI = reuse.UI
OTHER_GUID = reuse.OTHER_GUID
GUID = reuse.GUID


def _entry(number, before, after):
    return {'id': str(number), 'batch': str(number), 'kind': oe.POWER_KIND, 'key': oe.POWER_KEY,
            'before': before, 'after': after, 'status': 'applied',
            'created': '2026-11-07T00:00:00+00:00', 'updated': '2026-11-07T00:00:00+00:00'}


class RecordingPlan(reuse.PlanAdapter):
    def __init__(self):
        super().__init__()
        self.current = OTHER_GUID
        self.reverts = []
        self.reads = 0

    def available(self):
        self.reads += 1
        return super().available()

    def revert(self, key, value):
        self.reverts.append(value)
        super().revert(key, value)


class UndoAccountHelpers(reuse.FlowHelpers):
    def setUp(self):
        super().setUp()
        self.power = RecordingPlan()
        self.path.write_text(json.dumps({'schema': cj.SCHEMA,
                                         'entries': [_entry(1, GUID, OTHER_GUID)]}),
                             encoding='utf-8')
        self.owner = so.SAME
        self.owner_threads = []
        self.tweak_reads = []

    def probe(self):
        self.owner_threads.append(threading.current_thread() is threading.main_thread())
        return self.owner

    def panel(self):
        panel = super().panel()
        panel.changes_status = reuse.FakeVar()
        panel._session_owner_probe = self.probe
        panel.tweak_states = {'x': 'aplicado'}   # já mostrado: o desfazer releria
        panel.advanced_states = None
        panel._read_tweaks_work = lambda: self.tweak_reads.append(1) or {'tweaks': None}
        return panel

    def statuses(self, panel):
        return [e['status'] for e in panel.journal.entries()]


class UndoAccountFlowTests(UndoAccountHelpers):
    def assert_refused(self, panel, text):
        self.assertEqual(self.power.reverts, [])
        self.assertEqual(self.power.current, OTHER_GUID)
        self.assertEqual(self.statuses(panel), ['applied'])
        on_disk = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual([e['status'] for e in on_disk['entries']], ['applied'])
        # Com a conta recusada nada é relido (nem plano, nem ajustes).
        self.assertEqual(self.power.reads, 1)  # só o panel() de teste leu os planos
        self.assertEqual(self.tweak_reads, [])
        self.assertEqual(panel.changes_status.get(), text)
        self.assertIn(('warning', 'Desfazer tudo', text), self.shown)
        self.assertIn('Nada foi desfeito', text)
        self.assertIn('SUA própria conta', text)
        self.assertNotIn('Executar como administrador', text)  # FIX-P4-01-09 (R-85)
        self.assertEqual(self.owner_threads, [True])  # o Job falso roda na hora

    def test_other_account_undoes_nothing(self):
        self.owner = so.OTHER
        panel = self.panel()
        panel.undo_all_changes()
        self.assert_refused(panel, UI.CHANGES_OTHER_ACCOUNT_TEXT)
        self.assertIn('outra conta', UI.CHANGES_OTHER_ACCOUNT_TEXT)

    def test_unknown_account_undoes_nothing(self):
        self.owner = so.UNKNOWN
        panel = self.panel()
        panel.undo_all_changes()
        self.assert_refused(panel, UI.CHANGES_ACCOUNT_UNKNOWN_TEXT)
        self.assertIn('Não deu para confirmar', UI.CHANGES_ACCOUNT_UNKNOWN_TEXT)

    def test_probe_error_counts_as_unknown(self):
        def broken():
            raise OSError('sem resposta')
        panel = self.panel()
        panel._session_owner_probe = broken
        panel.undo_all_changes()
        self.assertEqual(self.power.reverts, [])
        self.assertEqual(self.statuses(panel), ['applied'])
        self.assertEqual(panel.changes_status.get(), UI.CHANGES_ACCOUNT_UNKNOWN_TEXT)

    def test_same_account_undoes_as_before(self):
        panel = self.panel()
        panel.undo_all_changes()
        self.assertEqual(self.power.reverts, [GUID])
        self.assertEqual(self.power.current, GUID)
        self.assertEqual(self.statuses(panel), ['reverted'])
        self.assertEqual(panel.changes_status.get(), UI.CHANGES_ONE_UNDONE_TEXT)
        self.assertEqual(self.tweak_reads, [1])
        self.assertFalse([s for s in self.shown if s[0] == 'warning'])

    def test_question_comes_before_account_check(self):
        # A recusa aparece depois do "Sim": "Não" não confere a conta nem desfaz.
        self.answer = False
        self.owner = so.OTHER
        panel = self.panel()
        panel.undo_all_changes()
        self.assertEqual(self.owner_threads, [])
        self.assertEqual(self.power.reverts, [])
        self.assertEqual(len(self.asked), 1)


class SlowProbeTests(UndoAccountHelpers):
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

        panel = self.panel()
        panel._session_owner_probe = slow
        panel._run_power_job = thread_job
        started = time.monotonic()
        panel.undo_all_changes()
        self.assertLess(time.monotonic() - started, 1.0)  # a tela não esperou a conta
        self.assertEqual(self.power.reverts, [])
        release.set()
        thread, box, done = jobs[0]
        thread.join(5)
        self.assertFalse(thread.is_alive())
        done(box['value'])
        self.assertEqual(self.owner_threads, [False])
        self.assertEqual(self.power.reverts, [GUID])


def _function(name):
    tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


class SourceTests(unittest.TestCase):
    def test_account_checked_inside_job_before_undo(self):
        start = _function('undo_all_changes')
        works = [n for n in start.body if isinstance(n, ast.FunctionDef) and n.name == 'work']
        self.assertEqual(len(works), 1)
        work = ast.unparse(works[0])
        self.assertIn('session_owner.session_owner(self._session_owner_probe)', work)
        self.assertLess(work.index('session_owner.session_owner'), work.index('undo_all()'))
        self.assertLess(work.index('session_owner.session_owner'), work.index('_read_plans_work'))
        # Fora do work (thread da tela) não há consulta da conta (R-56).
        outside = ast.unparse(ast.Module(body=[n for n in start.body if n is not works[0]],
                                         type_ignores=[]))
        self.assertNotIn('session_owner', outside)
        self.assertNotIn('session_owner.session_owner', ast.unparse(_function('_undo_all_done')))

    def test_done_handles_account_before_rereading(self):
        code = ast.unparse(_function('_undo_all_done'))
        self.assertIn("'account'", code)
        self.assertLess(code.index("'account'"), code.index('self._after_power_job'))


if __name__ == '__main__':
    unittest.main()
