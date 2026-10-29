"""P3-03 fatia 2a: plano de energia pelo diário de alterações, com desfazer item a item.

O powercfg, o PowerShell (ponto de restauração) e o teste de administrador são
SEMPRE simulados: as funções reais do módulo são trocadas por funções que falham
se forem chamadas. Arquivos só em TemporaryDirectory. Nenhum Checkpoint-Computer
nem powercfg real é executado.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import change_journal as cj  # noqa: E402
import optimization_engine as oe  # noqa: E402
from tk_helpers import track_tk_root  # noqa: E402

try:
    import tkinter as tk
    import optimization_ui as ou
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ou = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))

A = '381b4222-f694-41f0-9685-ff5bb260df2e'
B = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
C = 'a1841308-3541-4fab-bc81-f71556f20b4a'
UNKNOWN = '11111111-1111-1111-1111-111111111111'


def _forbidden(*args, **kwargs):
    raise AssertionError('powercfg/PowerShell real nunca deve ser chamado nos testes')


class FakePowercfg:
    """powercfg falso: guarda o plano ativo em memória e registra cada chamada."""

    def __init__(self, active=A, plans=((A, 'Equilibrado'), (B, 'Alto desempenho'),
                                        (C, 'Economia de energia'))):
        self.current = active
        self.plan_list = [{'guid': g, 'name': n, 'active': False} for g, n in plans]
        self.calls = []
        self.ignore_set = False
        self.active_error = None

    def plans(self):
        self.calls.append(('list',))
        return [dict(p) for p in self.plan_list]

    def active(self):
        self.calls.append(('get',))
        if self.active_error is not None:
            raise self.active_error
        return self.current

    def run(self, command, timeout=18):
        self.calls.append(tuple(command))
        if list(command[:2]) != ['powercfg', '/setactive']:
            raise AssertionError('comando inesperado')
        if not self.ignore_set:
            self.current = command[2]

    def setactive(self):
        return [c for c in self.calls if c[:2] == ('powercfg', '/setactive')]


class FakeRestorePointShell:
    """PowerShell falso para o ponto de restauração: devolve números de sequência."""

    def __init__(self, sequence=(5, 6), fail_checkpoint=False):
        self.sequence = list(sequence)
        self.fail_checkpoint = fail_checkpoint
        self.codes = []

    def __call__(self, code, timeout=22):
        self.codes.append(code)
        if 'Checkpoint-Computer' in code:
            if self.fail_checkpoint:
                raise oe.OptimizationError('falha simulada')
            return None
        return self.sequence.pop(0)

    def checkpoints(self):
        return [c for c in self.codes if 'Checkpoint-Computer' in c]


class SafetyNet(unittest.TestCase):
    def setUp(self):
        for name in ('_run', '_ps'):
            patcher = mock.patch.object(oe, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)


class PowerPlanAdapterTests(SafetyNet):
    def adapter(self, fake):
        return oe.PowerPlanAdapter(run=fake.run, active=fake.active, plans=fake.plans)

    def test_read_apply_and_revert(self):
        fake = FakePowercfg(active=A.upper())
        adapter = self.adapter(fake)
        self.assertEqual(adapter.kind, oe.POWER_KIND)
        self.assertEqual(adapter.label, 'Plano de energia')
        self.assertEqual(adapter.read(oe.POWER_KEY), A)
        adapter.apply(oe.POWER_KEY, B)
        self.assertEqual(fake.current, B)
        adapter.revert(oe.POWER_KEY, A)
        self.assertEqual(fake.current, A)
        self.assertEqual(fake.setactive(), [('powercfg', '/setactive', B),
                                            ('powercfg', '/setactive', A)])

    def test_guid_outside_list_is_refused_without_running(self):
        fake = FakePowercfg()
        adapter = self.adapter(fake)
        for method in (adapter.apply, adapter.revert):
            with self.assertRaises(oe.OptimizationError):
                method(oe.POWER_KEY, UNKNOWN)
        self.assertEqual(fake.setactive(), [])
        self.assertEqual(fake.current, A)

    def test_invalid_value_or_key_runs_nothing(self):
        fake = FakePowercfg()
        adapter = self.adapter(fake)
        for value in ('C:\\Windows', '', None, 1, A + ' & calc'):
            with self.assertRaises(oe.OptimizationError):
                adapter.apply(oe.POWER_KEY, value)
        with self.assertRaises(oe.OptimizationError):
            adapter.apply('outra_chave', B)
        with self.assertRaises(oe.OptimizationError):
            adapter.read('outra_chave')
        self.assertEqual(fake.calls, [])

    def test_journal_applies_and_undoes_power_plan(self):
        fake = FakePowercfg()
        journal = cj.ChangeJournal(self.tmp / 'diario.json', {oe.POWER_KIND: self.adapter(fake)},
                                   lambda description: True)
        ids = journal.apply_batch([{'kind': oe.POWER_KIND, 'key': oe.POWER_KEY, 'after': B}])
        entry = journal.entries()[0]
        self.assertEqual((entry['status'], entry['before'], entry['after']), ('applied', A, B))
        self.assertEqual(fake.current, B)
        self.assertEqual(journal.undo(ids[0]), (True, ''))
        self.assertEqual(journal.entries()[0]['status'], 'reverted')
        self.assertEqual(fake.current, A)
        self.assertEqual(journal.summary_lines()[0], '1. Plano de energia: desfeita.')


class RestorePointTests(SafetyNet):
    def test_confirmed_only_when_sequence_increases(self):
        shell = FakeRestorePointShell(sequence=(5, 6))
        self.assertIs(oe.create_restore_point('qualquer; Remove-Item x', run=shell,
                                              elevated=lambda: True), True)
        self.assertEqual(len(shell.checkpoints()), 1)
        # Descrição fixa: o texto recebido nunca entra no comando.
        self.assertIn(oe.RESTORE_POINT_DESCRIPTION, shell.checkpoints()[0])
        self.assertNotIn('Remove-Item', ' '.join(shell.codes))
        self.assertNotIn('Enable-ComputerRestore', ' '.join(shell.codes))

    def test_first_restore_point_from_zero(self):
        shell = FakeRestorePointShell(sequence=(0, 1))
        self.assertIs(oe.create_restore_point(run=shell, elevated=lambda: True), True)

    def test_same_number_is_refused(self):
        shell = FakeRestorePointShell(sequence=(7, 7))
        self.assertIs(oe.create_restore_point(run=shell, elevated=lambda: True), False)

    def test_checkpoint_failure_is_refused(self):
        shell = FakeRestorePointShell(sequence=(7, 8), fail_checkpoint=True)
        self.assertIs(oe.create_restore_point(run=shell, elevated=lambda: True), False)

    def test_unreadable_sequence_is_refused_before_checkpoint(self):
        for bad in (None, 'sete', True, 2.5):
            shell = FakeRestorePointShell(sequence=(bad, 9))
            self.assertIs(oe.create_restore_point(run=shell, elevated=lambda: True), False)
            self.assertEqual(shell.checkpoints(), [])

    def test_without_admin_runs_nothing(self):
        shell = FakeRestorePointShell()
        self.assertIs(oe.create_restore_point(run=shell, elevated=lambda: False), False)
        self.assertEqual(shell.codes, [])

    def test_default_without_admin_never_calls_powershell(self):
        # _ps real está trocado por _forbidden: se rodasse, o resultado seria False
        # pela exceção, então conferimos que nem foi chamado.
        self.assertIs(oe.create_restore_point(elevated=lambda: False), False)
        oe._ps.assert_not_called()

    def test_refused_restore_point_never_runs_setactive(self):
        cases = [
            ('mesmo número', FakeRestorePointShell(sequence=(3, 3)), lambda: True),
            ('comando falha', FakeRestorePointShell(sequence=(3, 4), fail_checkpoint=True), lambda: True),
            ('sem administrador', FakeRestorePointShell(), lambda: False),
        ]
        for name, shell, elevated in cases:
            with self.subTest(name):
                fake = FakePowercfg()
                adapter = oe.PowerPlanAdapter(run=fake.run, active=fake.active, plans=fake.plans)
                path = self.tmp / f'diario-{len(shell.codes)}-{name}.json'
                journal = cj.ChangeJournal(
                    path, {oe.POWER_KIND: adapter},
                    lambda d, s=shell, e=elevated: oe.create_restore_point(d, run=s, elevated=e))
                with self.assertRaises(cj.BatchRefused) as ctx:
                    journal.apply_batch([{'kind': oe.POWER_KIND, 'key': oe.POWER_KEY, 'after': B}])
                self.assertIn('ponto de restauração', str(ctx.exception))
                self.assertEqual(fake.setactive(), [])
                self.assertEqual(fake.current, A)
                self.assertEqual(journal.entries(), [])


class LegacyPowerJournalTests(SafetyNet):
    def write(self, record):
        path = self.tmp / 'otimizacao-energia-reversao.json'
        raw = record if isinstance(record, bytes) else json.dumps(record).encode('utf-8')
        path.write_bytes(raw)
        return path, raw

    def test_states(self):
        cases = [
            ({'schema': 'pcro-power-1', 'status': 'applied', 'previous': A, 'requested': B}, 'applied'),
            ({'schema': 'pcro-power-1', 'status': 'prepared', 'previous': A, 'requested': B}, 'pending'),
            ({'schema': 'pcro-power-1', 'status': 'failed', 'previous': A, 'requested': B}, 'pending'),
            ({'schema': 'pcro-power-1', 'status': 'reverted', 'previous': A, 'requested': B}, 'none'),
            ({'schema': 'outro', 'status': 'applied'}, 'unreadable'),
            ({'schema': 'pcro-power-1', 'status': 'estranho'}, 'unreadable'),
            (b'{nao e json', 'unreadable'),
            (b'\xff\xfe\x00', 'unreadable'),
            ([1, 2], 'unreadable'),
        ]
        for record, expected in cases:
            with self.subTest(expected=expected, record=str(record)[:40]):
                path, raw = self.write(record)
                self.assertEqual(oe.legacy_power_pending(path), expected)
                self.assertEqual(path.read_bytes(), raw)

    def test_missing_file_is_none(self):
        self.assertEqual(oe.legacy_power_pending(self.tmp / 'nao-existe.json'), 'none')
        self.assertFalse((self.tmp / 'nao-existe.json').exists())

    def test_directory_or_link_is_unreadable(self):
        folder = self.tmp / 'pasta.json'
        folder.mkdir()
        self.assertEqual(oe.legacy_power_pending(folder), 'unreadable')
        target, raw = self.write({'schema': 'pcro-power-1', 'status': 'reverted'})
        link = self.tmp / 'link.json'
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Sem permissão para criar link simbólico')
        self.assertEqual(oe.legacy_power_pending(link), 'unreadable')
        self.assertEqual(target.read_bytes(), raw)


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class PowerPanelTests(SafetyNet):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)
        self.fake = FakePowercfg()
        self.admin = {'value': True}
        self.restore_calls = []
        self.restore_ok = {'value': True}
        self.messages = []
        self.answers = []

    def restore_point(self, description):
        self.restore_calls.append(description)
        return self.restore_ok['value']

    def panel(self):
        adapter = oe.PowerPlanAdapter(run=self.fake.run, active=self.fake.active,
                                      plans=self.fake.plans)

        def ask(title, text):
            self.answers.append(title)
            return True

        panel = ou.OptimizationPanel(
            self.root, app_dir=self.tmp, state_dir=self.tmp, power_adapter=adapter,
            restore_point=self.restore_point, elevated_probe=lambda: self.admin['value'],
            ask=ask, show=lambda kind, title, text: self.messages.append((kind, title, text)))
        panel.pack()
        return panel

    @property
    def journal_file(self):
        return self.tmp / 'otimizacao-diario.json'

    def legacy_file(self):
        return self.tmp / 'otimizacao-energia-reversao.json'

    def entries(self):
        return json.loads(self.journal_file.read_text(encoding='utf-8'))['entries']

    def wait_idle(self, panel, seconds=5):
        """R-06: espera a thread terminar E a tela mostrar o fim."""
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.root.update()
            job = panel._power_job
            if not panel.power_busy and (job is None or not job.thread.is_alive()):
                break
            time.sleep(0.02)
        self.assertFalse(panel.power_busy)
        if panel._power_job is not None:
            self.assertFalse(panel._power_job.thread.is_alive())

    def choose(self, panel, guid):
        panel.load_plans()
        self.wait_idle(panel)
        index = [p['guid'] for p in panel.plans].index(guid)
        panel.plan_box.current(index)

    def apply(self, panel, guid):
        self.choose(panel, guid)
        panel.btn_apply.invoke()
        self.wait_idle(panel)

    def test_opening_panel_runs_no_command(self):
        panel = self.panel()
        self.root.update()
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.restore_calls, [])
        self.assertFalse(self.journal_file.exists())
        self.assertTrue(panel.btn_apply.instate(['!disabled']))
        self.assertTrue(panel.btn_revert.instate(['disabled']))
        self.assertFalse(panel.btn_legacy.winfo_manager())

    def test_apply_records_applied_entry(self):
        panel = self.panel()
        self.apply(panel, B)
        self.assertEqual(self.fake.current, B)
        self.assertEqual(len(self.restore_calls), 1)
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]['kind'], entries[0]['key'], entries[0]['status'],
                          entries[0]['before'], entries[0]['after']),
                         (oe.POWER_KIND, oe.POWER_KEY, 'applied', A, B))
        # A tela nem importa mais a troca antiga (fora do diário).
        self.assertFalse(hasattr(ou, 'safe_change_power_plan'))
        self.assertTrue(panel.btn_revert.instate(['!disabled']))
        self.assertIn('diário de alterações', panel.power_status.get())
        self.assertFalse(self.legacy_file().exists())

    def test_same_plan_changes_nothing(self):
        panel = self.panel()
        self.apply(panel, A)
        self.assertEqual(self.fake.setactive(), [])
        self.assertEqual(self.restore_calls, [])
        self.assertFalse(self.journal_file.exists())

    def test_without_admin_change_is_refused_and_explained(self):
        self.admin['value'] = False
        panel = self.panel()
        self.choose(panel, B)
        panel.btn_apply.invoke()
        self.wait_idle(panel)
        self.assertEqual(self.fake.setactive(), [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.answers, [])
        self.assertFalse(self.journal_file.exists())
        kind, _title, text = self.messages[-1]
        self.assertEqual(kind, 'warning')
        self.assertIn('Executar como administrador', text)
        self.assertIn('nunca pede', text)
        self.assertIsNone(panel._power_job)

    def test_restore_point_refused_explains_and_changes_nothing(self):
        self.restore_ok['value'] = False
        panel = self.panel()
        self.apply(panel, B)
        self.assertEqual(self.fake.setactive(), [])
        self.assertEqual(self.fake.current, A)
        text = self.messages[-1][2]
        self.assertIn('ponto de restauração', text)
        self.assertIn('24 horas', text)
        self.assertTrue(panel.btn_revert.instate(['disabled']))

    def test_undo_last_one_item_at_a_time(self):
        panel = self.panel()
        self.apply(panel, B)
        self.apply(panel, C)
        self.assertEqual(self.fake.current, C)
        panel.btn_revert.invoke()
        self.wait_idle(panel)
        self.assertEqual(self.fake.current, B)
        self.assertEqual([e['status'] for e in self.entries()], ['applied', 'reverted'])
        panel.btn_revert.invoke()
        self.wait_idle(panel)
        self.assertEqual(self.fake.current, A)
        self.assertEqual([e['status'] for e in self.entries()], ['reverted', 'reverted'])
        self.assertTrue(panel.btn_revert.instate(['disabled']))
        self.assertEqual(len(self.restore_calls), 2)  # desfazer não cria ponto novo

    def test_undo_works_without_admin(self):
        panel = self.panel()
        self.apply(panel, B)
        self.admin['value'] = False
        panel.btn_revert.invoke()
        self.wait_idle(panel)
        self.assertEqual(self.fake.current, A)
        self.assertEqual(self.entries()[0]['status'], 'reverted')

    def test_change_by_other_program_is_not_overwritten(self):
        panel = self.panel()
        self.apply(panel, B)
        self.fake.current = C  # outro programa trocou o plano
        before = len(self.fake.setactive())
        panel.btn_revert.invoke()
        self.wait_idle(panel)
        self.assertEqual(self.fake.current, C)
        self.assertEqual(len(self.fake.setactive()), before)
        self.assertEqual(self.messages[-1][2], cj.MSG_CHANGED_OUTSIDE)
        self.assertEqual(self.entries()[0]['status'], 'applied')

    def test_corrupted_journal_disables_buttons(self):
        raw = b'{isto nao e um diario'
        self.journal_file.write_bytes(raw)
        panel = self.panel()
        self.root.update()
        self.assertTrue(panel.btn_apply.instate(['disabled']))
        self.assertTrue(panel.btn_revert.instate(['disabled']))
        self.assertIn('ilegível', panel.power_status.get())
        self.choose(panel, B)
        panel.btn_apply.invoke()
        panel.apply_plan()  # mesmo chamando direto, nada acontece
        panel.revert_plan()
        self.wait_idle(panel)
        self.assertEqual(self.fake.setactive(), [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.journal_file.read_bytes(), raw)
        self.assertNotIn(str(self.tmp), panel.power_status.get())

    def test_journal_error_during_apply_disables_buttons(self):
        panel = self.panel()
        self.choose(panel, B)
        with mock.patch.object(panel.journal, 'apply_batch',
                               side_effect=cj.JournalError('Não foi possível gravar o diário de alterações.')):
            panel.btn_apply.invoke()
            self.wait_idle(panel)
        self.assertTrue(panel.btn_apply.instate(['disabled']))
        self.assertTrue(panel.btn_revert.instate(['disabled']))
        self.assertIn('Não foi possível gravar o diário', self.messages[-1][2])

    def test_legacy_applied_blocks_and_stays_byte_identical(self):
        raw = json.dumps({'schema': 'pcro-power-1', 'status': 'applied',
                          'previous': A, 'requested': B}).encode('utf-8')
        self.legacy_file().write_bytes(raw)
        self.fake.current = B
        panel = self.panel()
        self.root.update()
        self.assertTrue(panel.btn_apply.instate(['disabled']))
        self.assertEqual(panel.btn_legacy.winfo_manager(), 'pack')
        self.choose(panel, C)
        panel.apply_plan()
        self.wait_idle(panel)
        self.assertEqual(self.fake.setactive(), [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual(self.legacy_file().read_bytes(), raw)
        self.assertFalse(self.journal_file.exists())
        self.assertIn('versão antiga', self.messages[-1][2])

    def test_legacy_unreadable_blocks_and_stays_byte_identical(self):
        raw = b'\x00 registro quebrado'
        self.legacy_file().write_bytes(raw)
        panel = self.panel()
        self.root.update()
        self.assertTrue(panel.btn_apply.instate(['disabled']))
        panel.btn_legacy.invoke()
        self.wait_idle(panel)
        self.assertIn('não pôde ser lido', self.messages[-1][2])
        self.assertEqual(self.legacy_file().read_bytes(), raw)
        self.assertEqual(self.fake.calls, [])

    def test_legacy_undo_uses_old_revert_and_keeps_file(self):
        self.legacy_file().write_text(json.dumps(
            {'schema': 'pcro-power-1', 'status': 'applied', 'previous': A, 'requested': B}),
            encoding='utf-8')
        self.fake.current = B
        panel = self.panel()
        with mock.patch.object(oe, '_run', side_effect=self.fake.run), \
                mock.patch.object(oe, 'available_power_plans', side_effect=self.fake.plans), \
                mock.patch.object(oe, 'active_power_guid', side_effect=self.fake.active):
            panel.btn_legacy.invoke()
            self.wait_idle(panel)
        self.assertEqual(self.fake.current, A)
        record = json.loads(self.legacy_file().read_text(encoding='utf-8'))
        self.assertEqual((record['schema'], record['status']), ('pcro-power-1', 'reverted'))
        self.assertEqual(panel.legacy_state, 'none')
        self.assertFalse(panel.btn_legacy.winfo_manager())
        self.assertTrue(panel.btn_apply.instate(['!disabled']))
        self.assertFalse(self.journal_file.exists())
        self.assertEqual(self.restore_calls, [])

    # ---------- revisão R-18: casos que faltavam ----------
    def write_prepared(self, before=A, after=B):
        entry = {'id': '1', 'batch': '1', 'kind': oe.POWER_KIND, 'key': oe.POWER_KEY,
                 'before': before, 'after': after, 'status': 'prepared',
                 'created': '2026-10-28T00:00:00+00:00', 'updated': '2026-10-28T00:00:00+00:00'}
        self.journal_file.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': [entry]}),
                                     encoding='utf-8')

    def test_interrupted_item_back_to_before_is_recovered_and_batch_goes_on(self):
        self.write_prepared(before=A, after=B)
        panel = self.panel()
        self.root.update()
        self.assertEqual(self.fake.calls, [])  # abrir não confere nada
        with mock.patch.object(panel.journal, 'recover_interrupted',
                               wraps=panel.journal.recover_interrupted) as recover, \
                mock.patch.object(panel.journal, 'undo', side_effect=_forbidden), \
                mock.patch.object(panel.journal, 'undo_all', side_effect=_forbidden):
            self.apply(panel, C)
        recover.assert_called_once_with()
        self.assertEqual([e['status'] for e in self.entries()], ['reverted', 'applied'])
        self.assertEqual(self.fake.current, C)
        self.assertEqual(self.fake.setactive(), [('powercfg', '/setactive', C)])
        self.assertEqual(len(self.restore_calls), 1)

    def test_interrupted_item_with_unknown_plan_refuses_change(self):
        self.write_prepared(before=A, after=B)
        self.fake.current = C  # nem o valor de antes, nem o de depois
        panel = self.panel()
        self.choose(panel, B)
        with mock.patch.object(panel.journal, 'recover_interrupted',
                               wraps=panel.journal.recover_interrupted) as recover:
            panel.btn_apply.invoke()
            self.wait_idle(panel)
        recover.assert_called_once_with()
        self.assertEqual([e['status'] for e in self.entries()], ['unknown'])
        self.assertEqual(self.fake.setactive(), [])
        self.assertEqual(self.fake.current, C)
        self.assertEqual(self.restore_calls, [])
        kind, _title, text = self.messages[-1]
        self.assertEqual(kind, 'warning')
        self.assertIn('interrompida ou sem confirmação', text)

    def test_legacy_pending_or_failed_shows_check_text_and_runs_nothing(self):
        for status in ('prepared', 'failed'):
            with self.subTest(status=status):
                raw = json.dumps({'schema': 'pcro-power-1', 'status': status,
                                  'previous': A, 'requested': B}).encode('utf-8')
                self.legacy_file().write_bytes(raw)
                self.fake.calls.clear()
                self.messages.clear()
                with mock.patch.object(ou, 'revert_power_plan', side_effect=_forbidden) as old:
                    panel = self.panel()
                    self.root.update()
                    self.assertEqual(panel.legacy_state, 'pending')
                    self.assertTrue(panel.btn_apply.instate(['disabled']))
                    self.assertEqual(panel.btn_legacy.winfo_manager(), 'pack')
                    panel.btn_legacy.invoke()
                    self.wait_idle(panel)
                old.assert_not_called()
                self.assertEqual(self.messages[-1][2], ou.POWER_LEGACY_PENDING_TEXT)
                self.assertEqual(self.fake.calls, [])
                self.assertEqual(self.answers, [])
                self.assertEqual(self.legacy_file().read_bytes(), raw)
                self.assertTrue(panel.btn_apply.instate(['disabled']))
                self.assertFalse(self.journal_file.exists())
                panel.destroy()

    def power_text(self, panel):
        return panel.power_text.get('1.0', 'end')

    def test_plan_list_failure_with_user_path_shows_fixed_text(self):
        secret = 'C:\\Users\\Fulano\\AppData\\powercfg.log'
        for broken in ('plans', 'active'):
            with self.subTest(broken=broken):
                fake = FakePowercfg()

                def fail(*args, **kwargs):
                    raise oe.OptimizationError('Falha na consulta Windows: ' + secret)
                setattr(fake, broken, fail)
                self.fake = fake
                panel = self.panel()
                panel.load_plans()
                self.wait_idle(panel)
                text = self.power_text(panel)
                self.assertIn('Não foi possível ler os planos de energia do Windows.', text)
                self.assertNotIn('Fulano', text)
                self.assertNotIn('Fulano', panel.power_status.get())
                self.assertNotIn('Fulano', panel.note.get())
                self.assertEqual(fake.setactive(), [])
                panel.destroy()

    def test_read_failure_with_user_path_during_apply_hides_path(self):
        panel = self.panel()
        self.choose(panel, B)
        self.fake.active_error = oe.OptimizationError('Acesso negado em C:\\Users\\Fulano\\x')
        panel.btn_apply.invoke()
        self.wait_idle(panel)
        self.assertEqual(self.fake.setactive(), [])
        shown = ' '.join(m[2] for m in self.messages) + panel.power_status.get() + self.power_text(panel)
        self.assertNotIn('Fulano', shown)

    def test_unexpected_error_shows_generic_text(self):
        panel = self.panel()
        self.choose(panel, B)
        with mock.patch.object(panel.journal, 'apply_batch',
                               side_effect=RuntimeError('C:\\Users\\Fulano\\erro cru')):
            panel.btn_apply.invoke()
            self.wait_idle(panel)
        self.assertEqual(self.messages[-1], ('error', 'Plano de energia', ou.POWER_GENERIC_FAIL))
        self.assertEqual(panel.power_status.get(), ou.POWER_GENERIC_FAIL)
        self.assertNotIn('Fulano', ' '.join(m[2] for m in self.messages))
        self.assertTrue(panel.btn_apply.instate(['!disabled']))  # diário continua usável

    def test_legacy_messages_are_filtered(self):
        raw = json.dumps({'schema': 'pcro-power-1', 'status': 'applied',
                          'previous': A, 'requested': B}).encode('utf-8')
        known = 'O plano foi alterado por outro programa. Não sobrescrevi a escolha atual.'
        self.assertIn(known, ou._LEGACY_KNOWN_MESSAGES)
        cases = [('Acesso negado: C:\\Users\\Fulano\\x', ou.POWER_GENERIC_FAIL), (known, known)]
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.legacy_file().write_bytes(raw)
                self.messages.clear()
                panel = self.panel()
                with mock.patch.object(ou, 'revert_power_plan',
                                       side_effect=oe.OptimizationError(error)):
                    panel.btn_legacy.invoke()
                    self.wait_idle(panel)
                self.assertEqual(self.messages[-1][2], expected)
                self.assertNotIn('Fulano', panel.power_status.get())
                self.assertEqual(self.legacy_file().read_bytes(), raw)
                self.assertTrue(panel.btn_apply.instate(['disabled']))
                panel.destroy()


    # ---------- FIX-P3-03-01: leitura dos planos fora da thread da tela ----------
    def blocking_fake(self, method):
        """Troca um método do powercfg falso por um que espera um Event."""
        gate = threading.Event()
        self.addCleanup(gate.set)  # nunca deixar thread presa no fim do teste
        original = getattr(self.fake, method)

        def blocked(*args, **kwargs):
            gate.wait(5)
            return original(*args, **kwargs)
        setattr(self.fake, method, blocked)
        return gate

    def assert_power_buttons(self, panel, disabled):
        state = ['disabled'] if disabled else ['!disabled']
        self.assertTrue(panel.btn_refresh.instate(state))
        self.assertTrue(panel.btn_apply.instate(state))

    def test_plans_are_read_outside_main_thread(self):
        threads = []
        plans, active = self.fake.plans, self.fake.active

        def plans_spy():
            threads.append(threading.current_thread())
            return plans()

        def active_spy():
            threads.append(threading.current_thread())
            return active()
        self.fake.plans, self.fake.active = plans_spy, active_spy
        panel = self.panel()
        panel.load_plans()
        self.wait_idle(panel)
        self.assertEqual(len(threads), 2)
        for thread in threads:
            self.assertIsNot(thread, threading.main_thread())
        self.assertEqual([p['guid'] for p in panel.plans], [A, B, C])

    def test_load_plans_returns_at_once_and_disables_buttons(self):
        gate = self.blocking_fake('plans')
        panel = self.panel()
        started = time.monotonic()
        panel.load_plans()
        self.assertLess(time.monotonic() - started, 1.0)
        self.root.update()
        self.assertTrue(panel.power_busy)
        self.assert_power_buttons(panel, disabled=True)
        self.assertTrue(panel.btn_revert.instate(['disabled']))
        self.assertIn('somente leitura', panel.note.get())
        gate.set()
        self.wait_idle(panel)
        self.assert_power_buttons(panel, disabled=False)
        self.assertEqual([p['guid'] for p in panel.plans], [A, B, C])
        text = self.power_text(panel)
        self.assertIn('Equilibrado', text)
        self.assertIn('Antes de alterar:', text)
        self.assertEqual(panel.note.get(), 'Planos de energia consultados; nada foi alterado.')
        self.assertEqual(self.fake.setactive(), [])

    def test_refresh_disabled_during_apply_and_undo(self):
        gate = self.blocking_fake('run')  # antes do painel: o adaptador guarda a função
        panel = self.panel()
        self.choose(panel, B)
        panel.btn_apply.invoke()
        self.root.update()
        self.assertTrue(panel.power_busy)
        self.assertTrue(panel.btn_refresh.instate(['disabled']))
        gate.set()
        self.wait_idle(panel)
        self.assertTrue(panel.btn_refresh.instate(['!disabled']))
        self.assertEqual(self.fake.current, B)
        gate.clear()
        panel.btn_revert.invoke()
        self.root.update()
        self.assertTrue(panel.power_busy)
        self.assertTrue(panel.btn_refresh.instate(['disabled']))
        gate.set()
        self.wait_idle(panel)
        self.assertTrue(panel.btn_refresh.instate(['!disabled']))
        self.assertEqual(self.fake.current, A)

    def test_load_plans_while_busy_runs_nothing(self):
        panel = self.panel()
        panel.power_busy = True
        before = list(self.fake.calls)
        panel.load_plans()
        time.sleep(0.1)
        self.root.update()
        self.assertEqual(self.fake.calls, before)
        self.assertIsNone(panel._power_job)
        panel.power_busy = False

    def test_failed_refresh_keeps_previous_plans(self):
        panel = self.panel()
        self.choose(panel, B)
        self.fake.active_error = oe.OptimizationError('Acesso negado em C:\\Users\\Fulano\\x')
        panel.load_plans()
        self.wait_idle(panel)
        self.assertEqual([p['guid'] for p in panel.plans], [A, B, C])
        text = self.power_text(panel)
        self.assertIn('Não foi possível ler os planos de energia do Windows. Nada foi alterado.', text)
        self.assertNotIn('Fulano', text + panel.power_status.get() + panel.note.get())

    def test_closing_window_during_read_is_safe(self):
        gate = self.blocking_fake('plans')
        panel = self.panel()
        panel.load_plans()
        self.root.update()
        job = panel._power_job
        self.assertIsNotNone(job)
        panel.destroy()
        gate.set()
        job.thread.join(5)
        self.assertFalse(job.thread.is_alive())
        for _ in range(10):  # deixa o laço de eventos rodar: nenhum TclError
            self.root.update()
            time.sleep(0.02)
        self.assertEqual(self.fake.setactive(), [])

if __name__ == '__main__':
    unittest.main()
