"""FIX-M3-T3-01: a aba 4 (energia) também reaproveita o ponto de restauração do app.

A troca de plano passa a seguir o fluxo das abas 8 e 9 (FIX-M3-T3): num Job, antes
da pergunta, o app confere se o diário mudou por fora e se o ponto que ele mesmo
criou nas últimas 24 horas ainda existe; a pergunta cita o ponto; no aplicar o ponto
é conferido de novo e, se sumiu, a troca é recusada com ``MSG_REUSE_GONE`` sem
tentar criar outro.

Os testes de fluxo rodam também sem Tk: a tela é carregada com um ``tkinter`` falso
(só para importar o módulo) e os Jobs rodam na hora, com objetos falsos. Os testes
de janela de verdade pulam sem Tk. Tudo com Windows, administrador e plano de
energia falsos, e arquivos em TemporaryDirectory. Nenhum comando real.
"""
import ast
import importlib.util
import json
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import advanced_tweaks as at  # noqa: E402
import change_journal as cj  # noqa: E402
import optimization_engine as oe  # noqa: E402
import safe_tweaks as st  # noqa: E402
import session_owner as so  # noqa: E402
from test_change_journal_fix_m3_t3 import (  # noqa: E402
    GUID, NO_DISPLAY, FakePower, NoRealCommands, _iso, ou, tk, track_tk_root)

OTHER_GUID = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
REUSE_TEXT = 'O app vai usar o ponto de restauração que ele mesmo criou '


def _load_ui_without_tk():
    """Carrega optimization_ui com um tkinter falso, só para testar o fluxo sem Tk.

    O módulo fica com outro nome e os módulos falsos (e quem os importou agora) saem
    de sys.modules no fim, para não atrapalhar os outros testes."""
    if ou is not None:
        return ou
    stubs = {'tkinter': types.ModuleType('tkinter')}
    stubs['tkinter'].Frame = type('Frame', (), {})
    for sub in ('filedialog', 'messagebox', 'ttk'):
        module = types.ModuleType('tkinter.' + sub)
        setattr(stubs['tkinter'], sub, module)
        stubs['tkinter.' + sub] = module
    before = set(sys.modules)
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location('_optimization_ui_sem_tk',
                                                      ROOT / 'optimization_ui.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        fakes = set(map(id, stubs.values()))
        for name in set(sys.modules) - before:
            loaded = sys.modules[name]
            if name in stubs or any(id(v) in fakes for v in vars(loaded).values()):
                del sys.modules[name]
    return module


UI = _load_ui_without_tk()


class FakeVar:
    def __init__(self):
        self.value = ''

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeBox:
    """Caixa de planos falsa: o escolhido é o segundo (não o ativo)."""

    def current(self, *args):
        return 1


class PlanAdapter:
    """Plano de energia falso do diário: guarda o plano ativo e as trocas."""
    kind = oe.POWER_KIND
    label = 'Plano de energia'

    def __init__(self):
        self.current = GUID
        self.applied = []

    def available(self):
        return [{'guid': GUID, 'name': 'Equilibrado', 'active': self.current == GUID},
                {'guid': OTHER_GUID, 'name': 'Alto desempenho', 'active': self.current == OTHER_GUID}]

    def read(self, key):
        return self.current

    def apply(self, key, value):
        self.applied.append(value)
        self.current = value

    def revert(self, key, value):
        self.current = value


class FlowHelpers(NoRealCommands):
    """Painel montado sem janela: só os campos que o fluxo de aplicar usa."""

    def setUp(self):
        super().setUp()
        self.path = self.tmp / 'otimizacao-diario.json'
        self.power = PlanAdapter()
        self.created = []
        self.create_answer = {'sequence': 13}
        self.checks = []
        self.check_answers = []
        self.asked = []
        self.answer = True
        self.shown = []
        self.jobs = 0

    def note_point(self, minutes=9):
        point = {'sequence': 12, 'created': _iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))}
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': [], 'restore_point': point}),
                             encoding='utf-8')

    def create(self, description):
        self.created.append(description)
        return self.create_answer

    def confirm(self, record):
        self.checks.append(dict(record))
        return self.check_answers.pop(0) if self.check_answers else None

    def ask(self, title, text):
        self.asked.append((title, text))
        return self.answer

    def run_job(self, work, done):
        # Como o _run_power_job de verdade, mas na hora: falha do Job = {'status': 'error'}.
        self.jobs += 1
        try:
            value = work()
        except Exception:
            value = {'status': 'error'}
        done(value)

    def panel(self):
        panel = object.__new__(UI.OptimizationPanel)
        panel.journal = cj.ChangeJournal(self.path, {oe.POWER_KIND: self.power}, self.create, self.confirm)
        panel.journal_error = ''
        panel.journal_off_text = UI.POWER_JOURNAL_OFF_TEXT
        panel.legacy_state = 'none'
        panel.power_busy = False
        panel.power_adapter = self.power
        panel.plans = self.power.available()
        panel.plan_box = FakeBox()
        panel.state_dir = self.tmp
        panel.power_status = FakeVar()
        panel.tweaks_status = FakeVar()
        panel.advanced_status = FakeVar()
        panel.note = FakeVar()
        panel._ask = self.ask
        panel._ask_advanced = self.ask
        panel._show = lambda *a: self.shown.append(a)
        panel._is_elevated = lambda: True
        panel._run_power_job = self.run_job
        panel._update_power_buttons = lambda: None
        panel._after_power_job = lambda outcome: None
        panel._show_tweak_states = lambda *a, **k: None
        panel._show_advanced_states = lambda *a, **k: None
        return panel

    def journal_bytes(self):
        return self.path.read_bytes() if self.path.exists() else None


class PowerFlowTests(FlowHelpers):
    def test_app_point_is_named_in_the_question_and_reused(self):
        self.note_point()
        moment = datetime.now(timezone.utc) - timedelta(minutes=9)
        self.check_answers = [moment, moment]
        panel = self.panel()
        panel.apply_plan()
        when = st.restore_point_when(moment, datetime.now(timezone.utc))
        self.assertIn(REUSE_TEXT + when, self.asked[-1][1])
        self.assertIn('“Alto desempenho”', self.asked[-1][1])
        self.assertEqual(len(self.checks), 2)        # antes da pergunta e dentro do apply_batch
        self.assertEqual(self.created, [])            # nenhum ponto novo (Checkpoint-Computer)
        self.assertEqual(self.power.applied, [OTHER_GUID])
        self.assertEqual([e['status'] for e in panel.journal.entries()], ['applied'])
        self.assertIn('diário de alterações', panel.power_status.get())

    def test_reuse_flag_is_passed_to_apply_batch(self):
        self.note_point()
        moment = datetime.now(timezone.utc) - timedelta(minutes=9)
        self.check_answers = [moment, moment]
        panel = self.panel()
        calls = []
        original = panel.journal.apply_batch

        def spy(changes, reuse_restore_point=False):
            calls.append(reuse_restore_point)
            return original(changes, reuse_restore_point=reuse_restore_point)
        panel.journal.apply_batch = spy
        panel.apply_plan()
        self.assertEqual(calls, [True])

    def test_without_noted_point_the_question_says_a_new_one_is_created(self):
        panel = self.panel()
        panel.apply_plan()
        text = self.asked[-1][1]
        self.assertIn(st.RESTORE_POINT_NEW_TEXT, text)
        self.assertNotIn(REUSE_TEXT, text)
        self.assertEqual(self.checks, [])
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.power.applied, [OTHER_GUID])
        # O ponto novo fica anotado para a próxima troca.
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['restore_point']['sequence'], 13)

    def test_point_gone_between_question_and_apply_is_refused_without_creating(self):
        self.note_point()
        self.check_answers = [datetime.now(timezone.utc) - timedelta(minutes=9), None]
        panel = self.panel()
        before = self.journal_bytes()
        panel.apply_plan()
        self.assertIn(REUSE_TEXT, self.asked[-1][1])
        self.assertEqual(self.shown[-1], ('warning', 'Plano de energia', cj.MSG_REUSE_GONE))
        self.assertEqual(panel.power_status.get(), cj.MSG_REUSE_GONE)
        self.assertNotIn(UI.POWER_RESTORE_POINT_HELP, panel.power_status.get())
        self.assertEqual(self.created, [])
        self.assertEqual(self.power.applied, [])
        self.assertEqual(self.power.current, GUID)
        self.assertEqual(self.journal_bytes(), before)

    def test_failed_restore_point_gets_the_24h_help(self):
        self.create_answer = False
        panel = self.panel()
        panel.apply_plan()
        message = cj.MSG_RESTORE_POINT_FAILED + ' ' + UI.POWER_RESTORE_POINT_HELP
        self.assertEqual(self.shown[-1], ('warning', 'Plano de energia', message))
        self.assertEqual(panel.power_status.get(), message)
        self.assertEqual(self.power.applied, [])
        self.assertFalse(self.path.exists())

    def test_journal_changed_outside_is_refused_before_the_question(self):
        self.note_point()
        self.check_answers = [datetime.now(timezone.utc), datetime.now(timezone.utc)]
        panel = self.panel()
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': []}), encoding='utf-8')
        changed = self.journal_bytes()
        panel.apply_plan()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.checks, [])
        self.assertEqual(self.created, [])
        self.assertEqual(self.power.applied, [])
        self.assertEqual(self.journal_bytes(), changed)
        self.assertIsNone(panel.journal)
        self.assertEqual(self.shown[-1][0], 'error')
        self.assertIn(cj.MSG_OTHER_WINDOW, self.shown[-1][2])

    def test_no_runs_nothing(self):
        self.note_point()
        self.check_answers = [datetime.now(timezone.utc) - timedelta(minutes=9)]
        self.answer = False
        panel = self.panel()
        before = self.journal_bytes()
        panel.apply_plan()
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.jobs, 1)                # só a conferência, nenhum Job de aplicar
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(self.created, [])
        self.assertEqual(self.power.applied, [])
        self.assertEqual(self.journal_bytes(), before)
        self.assertEqual(panel.power_status.get(), UI.POWER_CANCEL_TEXT)

    def test_check_error_means_create_a_new_point(self):
        self.note_point()
        panel = self.panel()
        panel.journal.reusable_restore_point = lambda: (_ for _ in ()).throw(RuntimeError('x'))
        panel.apply_plan()
        self.assertIn(st.RESTORE_POINT_NEW_TEXT, self.asked[-1][1])
        self.assertEqual(len(self.created), 1)

    def test_failed_job_shows_fixed_text_and_does_not_ask(self):
        panel = self.panel()
        panel._power_reuse_work = lambda: 1 / 0
        panel.apply_plan()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.shown[-1], ('error', 'Plano de energia', UI.POWER_GENERIC_FAIL))
        self.assertEqual(self.power.applied, [])

    def test_refusals_before_any_job_stay(self):
        panel = self.panel()
        panel._is_elevated = lambda: False
        panel.apply_plan()
        self.assertEqual(self.jobs, 0)
        self.assertEqual(self.shown[-1][2], UI.POWER_ADMIN_TEXT)
        panel = self.panel()
        panel.legacy_state = 'applied'
        panel.apply_plan()
        self.assertEqual(self.jobs, 0)
        self.assertEqual(self.asked, [])

    def test_running_texts(self):
        self.assertEqual(UI.POWER_RUNNING_REUSE_TEXT,
                         'Conferindo o ponto de restauração e trocando o plano… Isto pode demorar um pouco.')
        self.assertEqual(UI.POWER_RUNNING_TEXT,
                         'Criando o ponto de restauração e trocando o plano… Isto pode demorar um pouco.')


class TweakTabsJournalChangedTests(FlowHelpers):
    """Abas 8 e 9: diário mudado por fora = mostra o erro e não pergunta."""

    def check_tab(self, work_name, ready, read_name, key):
        self.note_point()
        self.check_answers = [datetime.now(timezone.utc)]
        panel = self.panel()
        setattr(panel, read_name, lambda: {'account': so.SAME, key: []})
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': []}), encoding='utf-8')
        outcome = getattr(panel, work_name)()
        self.assertIn(cj.MSG_OTHER_WINDOW, outcome['journal'])
        self.assertNotIn('reuse_at', outcome)
        self.assertEqual(self.checks, [])
        ready(panel, outcome)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.created, [])
        self.assertIsNone(panel.journal)
        self.assertEqual(self.shown[-1][0], 'error')
        self.assertIn(cj.MSG_OTHER_WINDOW, self.shown[-1][2])
        return panel

    def test_tab_8(self):
        panel = self.check_tab('_checked_read_tweaks_for_apply_work',
                               lambda p, o: p._tweaks_ready(o), '_checked_read_tweaks_work', 'tweaks')
        self.assertIn(UI.TWEAKS_JOURNAL_OFF_TEXT, panel.tweaks_status.get())

    def test_tab_9(self):
        tweak = at.TWEAKS_BY_ID['mouse_precision']
        panel = self.check_tab('_checked_read_advanced_for_apply_work',
                               lambda p, o: p._advanced_ready(o, tweak), '_checked_read_advanced_work',
                               'advanced')
        self.assertIn(UI.ADVANCED_JOURNAL_OFF_TEXT, panel.advanced_status.get())

    def test_unchanged_journal_still_checks_the_point(self):
        self.note_point()
        moment = datetime.now(timezone.utc)
        self.check_answers = [moment]
        panel = self.panel()
        panel._checked_read_tweaks_work = lambda: {'account': so.SAME, 'tweaks': []}
        outcome = panel._checked_read_tweaks_for_apply_work()
        self.assertNotIn('journal', outcome)
        self.assertEqual(outcome['reuse_at'], moment)


class CheckUnchangedTests(NoRealCommands):
    def test_read_only_and_raises_when_changed(self):
        path = self.tmp / 'diario.json'
        calls = []
        journal = cj.ChangeJournal(path, {oe.POWER_KIND: PlanAdapter()},
                                   lambda d: calls.append(d), lambda r: calls.append(r))
        journal.check_unchanged()
        self.assertFalse(path.exists())   # não grava nada
        path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': []}), encoding='utf-8')
        with self.assertRaises(cj.JournalError) as ctx:
            journal.check_unchanged()
        self.assertEqual(str(ctx.exception), cj.MSG_OTHER_WINDOW)
        self.assertEqual(calls, [])


class TextTests(unittest.TestCase):
    NEW = 'usa o que o próprio app criou nas últimas 24 horas'

    def test_tab_4_texts_name_the_reuse(self):
        self.assertIn('cria antes um ponto de restauração do Windows ou ' + self.NEW,
                      UI.POWER_ADMIN_TEXT)
        self.assertIn('cria um ponto de restauração ou ' + self.NEW, UI.POWER_RESTORE_POINT_HELP)
        source = (ROOT / 'optimization_ui.py').read_text(encoding='utf-8')
        self.assertIn("'Ao aplicar: o app cria antes um ponto de restauração do Windows ou usa o que "
                      "o próprio app criou '\n               'nas últimas 24 horas, e anota a troca",
                      source)
        self.assertNotIn('cria antes um ponto de restauração do Windows e anota a troca', source)
        for text in (UI.POWER_ADMIN_TEXT, UI.POWER_RESTORE_POINT_HELP):
            for forbidden in ('\\', 'C:', 'HK'):
                self.assertNotIn(forbidden, text)

    def test_manual_names_the_reuse_for_tab_4(self):
        manual = ' '.join((ROOT / 'docs' / 'MANUAL.md').read_text(encoding='utf-8').split())
        self.assertIn('"4 Energia reversível", "8 Ajustes seguros" e "9 Ajustes avançados"). Antes de '
                      'mudar algo, o app cria um ponto de restauração do Windows ou ' + self.NEW, manual)


class SourceTests(unittest.TestCase):
    def functions(self, name):
        tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
        return {n.name: ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def test_advanced_tweaks_does_not_import_restore_point_when(self):
        tree = ast.parse((ROOT / 'advanced_tweaks.py').read_text(encoding='utf-8'))
        names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                 for alias in node.names]
        self.assertIn('restore_point_sentence', names)
        self.assertNotIn('restore_point_when', names)
        self.assertNotIn('noqa', (ROOT / 'advanced_tweaks.py').read_text(encoding='utf-8'))

    def test_apply_plan_asks_only_after_the_job(self):
        functions = self.functions('optimization_ui.py')
        self.assertNotIn('self._ask(', functions['apply_plan'])
        self.assertIn('self._run_power_job(self._power_reuse_work', functions['apply_plan'])
        self.assertIn('reuse_restore_point=reuse_at is not None', functions['_power_ready'])
        self.assertIn('restore_point_sentence(reuse_at)', functions['_power_ready'])
        self.assertIn('message == MSG_RESTORE_POINT_FAILED', functions['_apply_done'])
        self.assertIn('journal.check_unchanged()', functions['_journal_changed_outside'])


@unittest.skipIf(NO_DISPLAY, 'sem Tk ou sem tela')
class PowerGuiTests(NoRealCommands):
    """A aba 4 de verdade (com Tk): Jobs em thread, como no app."""

    def setUp(self):
        super().setUp()
        self.power = PlanAdapter()
        self.restore_calls = []
        self.check_answers = []
        self.checks = []
        self.asked = []
        self.shown = []
        point = {'sequence': 12, 'created': _iso(datetime.now(timezone.utc) - timedelta(minutes=9))}
        (self.tmp / 'otimizacao-diario.json').write_text(
            json.dumps({'schema': cj.SCHEMA, 'entries': [], 'restore_point': point}), encoding='utf-8')
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)
        self.panel = ou.OptimizationPanel(
            self.root, app_dir=self.tmp, state_dir=self.tmp, power_adapter=self.power,
            restore_point=self._restore_point, restore_point_check=self._check,
            elevated_probe=lambda: True, session_owner_probe=lambda: so.SAME,
            ask=self._ask, show=lambda *a: self.shown.append(a))
        self.panel.pack()
        self.settle()
        self.addCleanup(self._join)  # R-29: roda antes da limpeza da pasta.
        self.panel.load_plans()
        self.settle()
        self.panel.plan_box.current([p['guid'] for p in self.panel.plans].index(OTHER_GUID))

    def _restore_point(self, description):
        self.restore_calls.append(description)
        return False

    def _check(self, record):
        self.checks.append(dict(record))
        return self.check_answers.pop(0) if self.check_answers else None

    def _ask(self, title, text):
        self.asked.append((title, text))
        return True

    def _join(self):
        for name in ('_power_job', '_measure_job', '_checkup_job', '_idle_job', '_history_job'):
            job = getattr(self.panel, name, None)
            if job is not None:
                job.thread.join(timeout=5)

    def settle(self):
        panel = self.panel
        deadline = time.monotonic() + 5
        while (panel.power_busy or panel._history_job is not None) and time.monotonic() < deadline:
            job = panel._power_job
            if job is not None:
                job.thread.join(timeout=0.05)
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(panel.power_busy)

    def test_point_reused_and_plan_changed(self):
        moment = datetime.now(timezone.utc) - timedelta(minutes=9)
        self.check_answers = [moment, moment]
        self.panel.apply_plan()
        self.settle()
        self.assertIn(REUSE_TEXT, self.asked[-1][1])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(self.power.applied, [OTHER_GUID])

    def test_point_gone_before_apply(self):
        self.check_answers = [datetime.now(timezone.utc) - timedelta(minutes=9), None]
        self.panel.apply_plan()
        self.settle()
        self.assertEqual(self.shown[-1], ('warning', 'Plano de energia', cj.MSG_REUSE_GONE))
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.power.applied, [])

    def test_journal_changed_outside_does_not_ask(self):
        (self.tmp / 'otimizacao-diario.json').write_text(
            json.dumps({'schema': cj.SCHEMA, 'entries': []}), encoding='utf-8')
        self.panel.apply_plan()
        self.settle()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.power.applied, [])
        self.assertIn(cj.MSG_OTHER_WINDOW, self.shown[-1][2])


if __name__ == '__main__':
    unittest.main()
