"""P3-05 fatia 2: 2º ajuste avançado, agendamento de GPU acelerado por hardware (HKLM).

Só registro falso em memória (``tests/fake_winreg.py``, só HKLM aceito), ponto
de restauração falso e arquivos em TemporaryDirectory. Nenhum registro,
PowerShell ou subprocess de verdade.
"""
import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import advanced_tweaks as at  # noqa: E402
import change_journal as cj  # noqa: E402
from fake_winreg import FakeWinreg  # noqa: E402

GRAPHICS = r'SYSTEM\CurrentControlSet\Control\GraphicsDrivers'
VERSION = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
HKLM = FakeWinreg.HKEY_LOCAL_MACHINE
DWORD = FakeWinreg.REG_DWORD
SZ = FakeWinreg.REG_SZ
KEY = 'gpu_hw_scheduling'
WRITES = ('SetValueEx', 'DeleteValue', 'CreateKeyEx', 'DeleteKey', 'DeleteKeyEx')


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


class Base(unittest.TestCase):
    def setUp(self):
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.new_registry()
        self.restore_calls = []

    def new_registry(self):
        self.reg = FakeWinreg(hives=('HKLM',))
        self.machine = at.MachineDwordAdapter(registry=self.reg)
        self.user_reg = FakeWinreg()
        self.user = at.AdvancedRegistryAdapter(registry=self.user_reg)

    def build(self, value='19045', kind=None):
        self.reg.put(VERSION, 'CurrentBuildNumber', value, SZ if kind is None else kind, hive=HKLM)

    def mode(self, value=1, kind=DWORD):
        self.reg.put(GRAPHICS, 'HwSchMode', value, kind, hive=HKLM)

    def current(self):
        return self.reg.get(GRAPHICS, 'HwSchMode', hive=HKLM)

    def writes(self):
        return [c for c in self.reg.calls if c[0] in WRITES]

    def snapshot(self):
        return {path: dict(values) for path, values in self.reg.machine_keys.items()}

    def restore_point(self, description):
        self.restore_calls.append(description)
        return True

    def journal(self):
        return cj.ChangeJournal(self.tmp / 'diario.json',
                                {at.ADVANCED_KIND: self.user, at.MACHINE_KIND: self.machine},
                                self.restore_point)

    def gpu_state(self):
        return at.state_for(at.read_states(self.user, self.machine), KEY)


class ClosedListTests(Base):
    def test_the_list_has_the_gpu_tweak_with_one_dword(self):
        self.assertEqual([t.id for t in at.ADVANCED_TWEAKS], ['mouse_precision', KEY])
        tweak = at.TWEAKS_BY_ID[KEY]
        self.assertEqual(tweak.name, 'Agendamento de GPU acelerado por hardware ligado')
        self.assertEqual(tweak.needs_build, 19041)
        self.assertIsNone(at.TWEAKS_BY_ID['mouse_precision'].needs_build)
        (value,) = tweak.values
        self.assertEqual((value.key, value.path, value.names, value.desired, value.kind, value.scope),
                         (KEY, GRAPHICS, ('HwSchMode',), (2,), at.MACHINE_KIND, 'computador'))
        self.assertEqual(value.label, 'Agendamento de GPU por hardware')
        self.assertEqual(at.TWEAK_VALUES[KEY].kind, 'hklm_dword_advanced')
        self.assertEqual(at.MACHINE_KIND, 'hklm_dword_advanced')
        self.assertEqual(at.TWEAK_VALUES['mouse_precision'].scope, 'conta')
        self.assertEqual(at.TWEAK_VALUES['mouse_precision'].kind, at.ADVANCED_KIND)
        self.assertTrue(cj._valid_key(at.MACHINE_KIND))
        self.assertEqual(self.machine.kind, at.MACHINE_KIND)
        self.assertEqual(self.machine.label_for(KEY), 'Agendamento de GPU por hardware')

    def test_each_adapter_only_accepts_its_own_keys(self):
        for call in (lambda: self.machine.read('mouse_precision'),
                     lambda: self.machine.apply('mouse_precision', 2),
                     lambda: self.machine.revert('mouse_precision', 1),
                     lambda: self.user.read(KEY),
                     lambda: self.user.apply(KEY, '0;0;0'),
                     lambda: self.user.revert(KEY, ';;')):
            with self.assertRaises(at.AdvancedTweakError):
                call()
        self.assertEqual(self.reg.calls, [])
        self.assertEqual(self.user_reg.calls, [])

    def test_texts_say_all_accounts_restart_and_the_downside(self):
        tweak = at.TWEAKS_BY_ID[KEY]
        for field in ('name', 'what', 'downside', 'when'):
            text = getattr(tweak, field)
            self.assertNotIn('\\', text)
            self.assertNotIn('HK', text)
            self.assertNotIn('HwSch', text)
        self.assertIn('Configurações > Sistema > Tela > Elementos gráficos', tweak.what)
        self.assertIn('Alterar configurações gráficas padrão', tweak.what)
        for part in ('jogos', 'drivers', 'captura', 'gravação', 'travar', 'todas as contas'):
            self.assertIn(part, tweak.downside)
        self.assertIn('reiniciar o computador', tweak.when)
        self.assertIn('desfazer também', tweak.when)
        self.assertIn('nunca reinicia', tweak.when)
        question = at.confirmation_text(tweak)
        self.assertIn('neste computador (todas as contas)', question)
        self.assertNotIn('na sua conta', question)
        for part in ('todas as contas', 'reiniciar', 'Lado ruim: ' + tweak.downside, 'ponto de restauração',
                     'Desfazer tudo'):
            self.assertIn(part, question)
        mouse = at.confirmation_text(at.TWEAKS_BY_ID['mouse_precision'])
        self.assertIn('na sua conta do Windows', mouse)
        self.assertNotIn('todas as contas', mouse)
        intro = '\n'.join(at.intro_lines())
        self.assertNotIn('só na sua conta do Windows;', intro)
        self.assertIn(tweak.downside, intro)

    def test_source_writes_hklm_only_in_the_machine_adapter_and_never_creates_or_deletes(self):
        source = (ROOT / 'advanced_tweaks.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        classes = {n.name: ast.unparse(n) for n in tree.body if isinstance(n, ast.ClassDef)}
        self.assertNotIn('HKEY_LOCAL_MACHINE', classes['AdvancedRegistryAdapter'])
        self.assertIn('HKEY_LOCAL_MACHINE', classes['MachineDwordAdapter'])
        machine = classes['MachineDwordAdapter']
        for forbidden in ('CreateKey', 'DeleteValue', 'DeleteKey', 'HKEY_CURRENT_USER'):
            self.assertNotIn(forbidden, machine)
        self.assertIn('KEY_WOW64_64KEY', machine)

    def test_default_adapter_does_not_touch_winreg_on_construction(self):
        adapter = at.MachineDwordAdapter()
        with mock.patch.object(at, '_is_windows', return_value=False):
            with self.assertRaises(at.AdvancedTweakError):
                adapter.read(KEY)


class StateTests(Base):
    def test_new_build_with_1_is_not_applied_and_with_2_is_applied(self):
        for build in ('19041', '19045', '22631', '26100'):
            with self.subTest(build=build):
                self.new_registry()
                self.build(build)
                self.mode(1)
                self.assertEqual(self.machine.read(KEY), 1)
                self.assertEqual(self.gpu_state(), {
                    'id': KEY, 'state': 'not_applied',
                    'changes': [{'kind': at.MACHINE_KIND, 'key': KEY, 'after': 2}]})
                self.mode(2)
                self.assertEqual(self.gpu_state(), {'id': KEY, 'state': 'applied', 'changes': []})
                self.assertEqual(self.writes(), [])
        self.assertIn('Agendamento de GPU acelerado por hardware ligado: já aplicado.',
                      '\n'.join(at.state_lines(at.read_states(self.user, self.machine))))

    def test_opens_with_read_and_64_bit_view(self):
        self.build()
        self.mode(1)
        self.machine.read(KEY)
        opens = [c for c in self.reg.calls if c[0] == 'OpenKey']
        self.assertEqual({c[2] for c in opens}, {FakeWinreg.KEY_READ | FakeWinreg.KEY_WOW64_64KEY})
        self.assertEqual([c[1] for c in opens], [VERSION, GRAPHICS])   # a versão vem antes

    def assert_unsupported(self):
        before = self.snapshot()
        state = self.gpu_state()
        self.assertEqual(state, {'id': KEY, 'state': 'unsupported', 'changes': []})
        with self.assertRaises(at.NotSupportedError):
            self.machine.read(KEY)
        for call in (lambda: self.machine.apply(KEY, 2), lambda: self.machine.revert(KEY, 1)):
            with self.assertRaises(at.AdvancedTweakError):
                call()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.writes(), [])
        text = '\n'.join(at.state_lines([state]))
        self.assertIn(at.STATE_TEXT['unsupported'], text)
        self.assertIn('o app não mexe', text)
        self.assertNotIn('não oferece', text)

    def test_value_absent_out_of_list_or_other_type_is_unsupported(self):
        cases = {'ausente': None, 'zero': (0, DWORD), 'tres': (3, DWORD), 'texto': ('1', SZ),
                 'qword': (1, FakeWinreg.REG_QWORD), 'bool': (True, DWORD), 'binario': (b'\x01', 3),
                 'negativo': (-1, DWORD), 'grande': (2 ** 32, DWORD)}
        for name, case in cases.items():
            with self.subTest(case=name):
                self.new_registry()
                self.build()
                self.reg.put(GRAPHICS, 'OutroValor', 5, DWORD, hive=HKLM)
                if case is not None:
                    self.mode(*case)
                self.assert_unsupported()

    def test_key_absent_is_unsupported_and_is_not_created(self):
        self.build()
        self.assert_unsupported()
        self.assertNotIn(GRAPHICS.lower(), self.reg.machine_keys)

    def test_old_unreadable_or_strange_build_is_unsupported(self):
        cases = {'18363': ('18363', SZ), '19040': ('19040', SZ), 'abc': ('abc', SZ),
                 'vazio': ('', SZ), 'espaco': (' 19045', SZ), 'outra lingua': ('١٩٠٤٥', SZ),
                 'dword': (19045, DWORD), 'expansivel': ('19045', FakeWinreg.REG_EXPAND_SZ),
                 'ausente': None}
        for name, case in cases.items():
            with self.subTest(case=name):
                self.new_registry()
                self.mode(1)
                if case is not None:
                    self.build(*case)
                self.assert_unsupported()
                # Build ruim: nem chega a ler o HwSchMode.
                self.assertFalse([c for c in self.reg.calls if c[0] == 'QueryValueEx'
                                  and c[2] == 'HwSchMode'])

    def test_neutral_text_for_absent_value_and_other_type(self):
        # R-57: o estado junta causas diferentes; o texto vale para todas e não culpa a placa.
        for name, case in {'ausente': None, 'texto': ('1', SZ),
                           'qword': (1, FakeWinreg.REG_QWORD)}.items():
            with self.subTest(case=name):
                self.new_registry()
                self.build()
                self.reg.put(GRAPHICS, 'OutroValor', 5, DWORD, hive=HKLM)
                if case is not None:
                    self.mode(*case)
                with self.assertRaises(at.NotSupportedError) as raised:
                    self.machine.read(KEY)
                message = str(raised.exception)
                text = '\n'.join(at.state_lines([self.gpu_state()]))
                for shown in (message, text):
                    self.assertIn('não encontrou esta opção num formato que ele sabe mudar com '
                                  'segurança', shown)
                    self.assertIn('o app não mexe', shown)
                    self.assertNotIn('não oferece', shown)
                    self.assertNotIn('placa de vídeo', shown)
                    self.assertIn('a opção não aparece neste PC', shown)
                    self.assertNotIn('nunca usada', shown)
                self.assertEqual(message, at.MSG_NOT_SUPPORTED)
                self.assertIn('Nada foi alterado', message)
                self.assertIn('Configurações > Sistema > Tela > Elementos gráficos', message)

    def test_build_unreadable_by_permission_or_system_error_is_unreadable(self):
        # Revisão 2 da PR #206: erro de permissão ou do sistema não é "não suportado".
        errors = {'permissao': PermissionError(5, r'Acesso negado C:\Users\Fulano'),
                  'sistema': OSError(1450, 'recursos insuficientes')}
        for name, error in errors.items():
            with self.subTest(case=name):
                self.new_registry()
                self.build()
                self.mode(1)
                real = self.reg.QueryValueEx

                def query(key, value_name, _error=error, _real=real):
                    if value_name == 'CurrentBuildNumber':
                        raise _error
                    return _real(key, value_name)
                self.reg.QueryValueEx = query
                before = self.snapshot()
                state = self.gpu_state()
                self.assertEqual(state, {'id': KEY, 'state': 'unreadable', 'changes': []})
                text = '\n'.join(at.state_lines([state]))
                self.assertIn(at.STATE_TEXT['unreadable'], text)
                self.assertNotIn('Fulano', text)
                for call in (lambda: self.machine.read(KEY), lambda: self.machine.apply(KEY, 2),
                             lambda: self.machine.revert(KEY, 1)):
                    with self.assertRaises(OSError):
                        call()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.writes(), [])
                self.assertFalse([c for c in self.reg.calls if c[0] == 'QueryValueEx'
                                  and c[2] == 'HwSchMode'])

    def test_build_absent_or_out_of_pattern_is_unsupported(self):
        for case in (None, ('19045a', SZ)):
            with self.subTest(case=case):
                self.new_registry()
                self.mode(1)
                if case is not None:
                    self.build(*case)
                self.assertEqual(self.gpu_state()['state'], 'unsupported')

    def test_reading_hwschmode_fails_is_unreadable(self):
        self.build()
        self.mode(1)
        self.reg.fail_read.add('HwSchMode')
        state = self.gpu_state()
        self.assertEqual(state['state'], 'unreadable')
        self.assertEqual(state['changes'], [])
        self.assertNotIn('Fulano', '\n'.join(at.state_lines([state])))

    def test_without_machine_adapter_the_gpu_tweak_is_unreadable(self):
        states = at.read_states(self.user)
        self.assertEqual([s['id'] for s in states], ['mouse_precision', KEY])
        self.assertEqual(at.state_for(states, KEY), {'id': KEY, 'state': 'unreadable', 'changes': []})
        self.assertEqual(self.reg.calls, [])


class OnlyTheListTests(Base):
    def test_apply_only_accepts_2_and_revert_only_accepts_1(self):
        self.build()
        self.mode(1)
        for bad in (1, 0, 3, True, False, 2.0, '2', None, (2,), -2):
            with self.subTest(apply=bad):
                with self.assertRaises(at.AdvancedTweakError) as raised:
                    self.machine.apply(KEY, bad)
                self.assertEqual(str(raised.exception), at.MSG_BAD_VALUE)
        self.mode(2)
        for bad in (2, 0, 3, True, False, 1.0, '1', None, (1,)):
            with self.subTest(revert=bad):
                with self.assertRaises(at.AdvancedTweakError) as raised:
                    self.machine.revert(KEY, bad)
                self.assertEqual(str(raised.exception), at.MSG_BAD_VALUE)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.current(), (2, DWORD))

    def test_apply_writes_one_dword_with_set_value_access(self):
        self.build()
        self.mode(1)
        self.machine.apply(KEY, 2)
        self.assertEqual(self.current(), (2, DWORD))
        sets = [c for c in self.reg.calls if c[0] == 'SetValueEx']
        self.assertEqual(sets, [('SetValueEx', GRAPHICS.lower(), 'HwSchMode', DWORD, 2)])
        write_open = [c for c in self.reg.calls if c[0] == 'OpenKey' and c[1] == GRAPHICS][-1]
        self.assertTrue(write_open[2] & FakeWinreg.KEY_SET_VALUE)
        self.assertTrue(write_open[2] & FakeWinreg.KEY_WOW64_64KEY)
        self.machine.revert(KEY, 1)
        self.assertEqual(self.current(), (1, DWORD))

    def test_value_changed_to_out_of_list_before_writing_is_refused(self):
        self.build()
        self.mode(1)
        real = self.reg.OpenKey

        def changed_by_another_program(hive, path, reserved=0, access=FakeWinreg.KEY_READ):
            if access & FakeWinreg.KEY_SET_VALUE:
                self.mode(3)
            return real(hive, path, reserved, access)
        self.reg.OpenKey = changed_by_another_program
        with self.assertRaises(at.NotSupportedError):
            self.machine.apply(KEY, 2)
        self.assertEqual(self.current(), (3, DWORD))
        self.assertEqual(self.writes(), [])

    def test_write_failure_is_refused_and_the_journal_marks_failed(self):
        self.build()
        self.mode(1)
        self.reg.fail_set.add('HwSchMode')
        with self.assertRaises(at.AdvancedTweakError) as raised:
            self.machine.apply(KEY, 2)
        self.assertEqual(str(raised.exception), at.MSG_WRITE_FAILED_ONE)
        self.assertIn('nada foi mudado neste ajuste', str(raised.exception))
        self.assertNotIn('voltou', str(raised.exception))
        self.assertNotIn('Fulano', str(raised.exception))
        self.assertEqual(self.current(), (1, DWORD))
        journal = self.journal()
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch(self.gpu_state()['changes'])
        self.assertEqual(journal.entries()[0]['status'], 'failed')
        self.assertEqual(self.current(), (1, DWORD))

    def test_never_creates_or_deletes_keys_or_values(self):
        self.build()
        self.mode(1)
        spied = []
        for name in ('CreateKeyEx', 'DeleteValue', 'DeleteKey', 'DeleteKeyEx'):
            setattr(self.reg, name, lambda *a, _n=name, **k: spied.append(_n))
        journal = self.journal()
        journal.apply_batch(self.gpu_state()['changes'])
        journal.recheck()
        journal.undo_all()
        self.new_registry()   # chave ausente: desfazer também não cria nada
        for name in ('CreateKeyEx', 'DeleteValue', 'DeleteKey', 'DeleteKeyEx'):
            setattr(self.reg, name, lambda *a, _n=name, **k: spied.append(_n))
        self.build()
        for call in (lambda: self.machine.apply(KEY, 2), lambda: self.machine.revert(KEY, 1)):
            with self.assertRaises(at.AdvancedTweakError):
                call()
        self.assertEqual(spied, [])


class JournalTests(Base):
    def test_apply_recheck_and_undo_all_go_back_to_1(self):
        self.build()
        self.mode(1)
        journal = self.journal()
        ids = journal.apply_batch(self.gpu_state()['changes'])
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(self.restore_calls), 1)
        self.assertEqual(self.current(), (2, DWORD))
        entry = journal.entries()[0]
        self.assertEqual((entry['kind'], entry['key'], entry['status']), (at.MACHINE_KIND, KEY, 'applied'))
        self.assertIs(type(entry['before']), int)
        self.assertIs(type(entry['after']), int)
        self.assertEqual((entry['before'], entry['after']), (1, 2))
        self.assertEqual(journal.summary_lines()[0], '1. Agendamento de GPU por hardware: aplicada.')
        # O diário gravado em disco guarda número, não texto.
        reopened = cj.ChangeJournal(self.tmp / 'diario.json',
                                    {at.ADVANCED_KIND: self.user, at.MACHINE_KIND: self.machine},
                                    self.restore_point)
        self.assertIs(type(reopened.entries()[0]['before']), int)
        result = journal.recheck()
        self.assertEqual(result['changed'], [])
        self.assertEqual(journal.entries()[0]['status'], 'applied')
        done, pending, reason = journal.undo_all()
        self.assertEqual((len(done), pending, reason), (1, [], ''))
        self.assertEqual(self.current(), (1, DWORD))
        self.assertEqual(self.gpu_state()['state'], 'not_applied')

    def test_recheck_sees_undo_done_in_settings(self):
        self.build()
        self.mode(1)
        journal = self.journal()
        journal.apply_batch(self.gpu_state()['changes'])
        self.mode(1)   # desligado por fora, em Configurações
        result = journal.recheck()
        self.assertEqual(len(result['changed']), 1)
        self.assertEqual(journal.entries()[0]['status'], 'reverted')

    def test_undo_all_with_value_changed_to_3_outside_writes_nothing(self):
        self.build()
        self.mode(1)
        journal = self.journal()
        journal.apply_batch(self.gpu_state()['changes'])
        self.mode(3)   # mudado por fora (outro programa)
        self.reg.calls.clear()
        done, pending, reason = journal.undo_all()
        self.assertEqual(done, [])
        self.assertTrue(pending)
        self.assertEqual(self.current(), (3, DWORD))
        self.assertEqual(self.writes(), [])

    def test_mouse_and_gpu_go_through_the_same_journal_with_their_own_kinds(self):
        self.build()
        self.mode(1)
        for name, value in zip(('MouseSpeed', 'MouseThreshold1', 'MouseThreshold2'), ('1', '6', '10')):
            self.user_reg.put(r'Control Panel\Mouse', name, value, SZ)
        states = at.read_states(self.user, self.machine)
        changes = [c for s in states for c in s['changes']]
        self.assertEqual([(c['kind'], c['key']) for c in changes],
                         [(at.ADVANCED_KIND, 'mouse_precision'), (at.MACHINE_KIND, KEY)])
        journal = self.journal()
        journal.apply_batch(changes)
        self.assertEqual(self.current(), (2, DWORD))
        journal.undo_all()
        self.assertEqual(self.current(), (1, DWORD))
        self.assertEqual(self.user_reg.get(r'Control Panel\Mouse', 'MouseSpeed'), ('1', SZ))


if __name__ == '__main__':
    unittest.main()
