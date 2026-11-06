"""P3-05 fatia 1: ajustes avançados, 1º ajuste (aceleração do mouse).

Só registro falso em memória (``tests/fake_winreg.py``), ponto de restauração
falso e arquivos em TemporaryDirectory. Nenhum registro, PowerShell,
SystemParametersInfo ou subprocess de verdade.
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

MOUSE = r'Control Panel\Mouse'
NAMES = ('MouseSpeed', 'MouseThreshold1', 'MouseThreshold2')
SZ = FakeWinreg.REG_SZ


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
        self.reg = FakeWinreg()
        self.adapter = at.AdvancedRegistryAdapter(registry=self.reg)
        self.restore_calls = []
        self.restore_ok = True

    def windows_default(self):
        """O padrão do Windows: "Aumentar precisão do ponteiro" ligado."""
        for name, value in zip(NAMES, ('1', '6', '10')):
            self.reg.put(MOUSE, name, value, SZ)
        self.reg.put(MOUSE, 'MouseSensitivity', '10', SZ)

    def values(self):
        return tuple(self.reg.get(MOUSE, name) for name in NAMES)

    def writes(self):
        return [c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue', 'CreateKeyEx')]

    def restore_point(self, description):
        self.restore_calls.append(description)
        return self.restore_ok

    def journal(self):
        return cj.ChangeJournal(self.tmp / 'diario.json', {at.ADVANCED_KIND: self.adapter},
                                self.restore_point)


class ClosedListTests(Base):
    def test_list_is_exactly_the_mouse_tweak_with_three_text_values(self):
        self.assertIsInstance(at.ADVANCED_TWEAKS, tuple)
        self.assertEqual([t.id for t in at.ADVANCED_TWEAKS], ['mouse_precision'])
        tweak = at.TWEAKS_BY_ID['mouse_precision']
        self.assertEqual(len(tweak.values), 1)
        value = tweak.values[0]
        self.assertEqual((value.key, value.path, value.names, value.desired),
                         ('mouse_precision', MOUSE, NAMES, ('0', '0', '0')))
        self.assertEqual(set(at.TWEAK_VALUES), {'mouse_precision'})
        self.assertEqual(at.ADVANCED_KIND, 'hkcu_sz_advanced')
        self.assertTrue(cj._valid_key(at.ADVANCED_KIND))
        self.assertTrue(cj._valid_key(value.key))

    def test_texts_are_simple_portuguese_with_the_downside(self):
        tweak = at.TWEAKS_BY_ID['mouse_precision']
        for field in ('name', 'what', 'downside', 'when'):
            text = getattr(tweak, field)
            self.assertTrue(text.strip())
            self.assertNotIn('\\', text)
            self.assertNotIn('HK', text)
            self.assertNotIn('Mouse' + 'Speed', text)
        self.assertIn('Aumentar precisão do ponteiro', tweak.what)
        self.assertIn('sair da sua conta', tweak.when)
        self.assertIn('entrar de novo', tweak.when)
        self.assertEqual(self.adapter.label_for('mouse_precision'), 'Aceleração do mouse')
        self.assertEqual(self.adapter.label_for('outro'), self.adapter.label)

    def test_source_has_no_commands_hklm_or_system_calls(self):
        source = (ROOT / 'advanced_tweaks.py').read_text(encoding='utf-8')
        for forbidden in ('HKEY_LOCAL_MACHINE', 'HKLM', 'Defender', 'WindowsUpdate', 'Policies',
                          'Services', 'subprocess', 'powershell', 'SystemParametersInfo', 'ctypes',
                          'BIOS', 'os.system'):
            self.assertNotIn(forbidden, source)
        tree = ast.parse(source)
        calls = {n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertNotIn('DeleteKey', calls)
        self.assertNotIn('DeleteKeyEx', calls)
        # winreg só é importado dentro da função, na hora de usar.
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertNotIn('winreg', ast.unparse(ast.Module(body=top, type_ignores=[])))

    def test_default_adapter_does_not_touch_winreg_on_construction(self):
        adapter = at.AdvancedRegistryAdapter()
        self.assertEqual(adapter.kind, at.ADVANCED_KIND)
        with mock.patch.object(at, '_is_windows', return_value=False):
            with self.assertRaises(at.AdvancedTweakError):
                adapter.read('mouse_precision')


class OnlyTheListTests(Base):
    # Critério 1: só grava os valores da lista; chave/valor fora da lista recusados sem gravar.
    def test_key_outside_the_list_is_refused_without_touching_the_registry(self):
        for key in ('outro', 'mouse_precision ', 'MOUSE_PRECISION', '', None, 1, MOUSE,
                    'MouseSpeed', 'game_mode'):
            with self.subTest(key=key):
                for call in (lambda: self.adapter.read(key),
                             lambda: self.adapter.apply(key, '0;0;0'),
                             lambda: self.adapter.revert(key, '1;6;10')):
                    with self.assertRaises(at.AdvancedTweakError):
                        call()
        self.assertEqual(self.reg.calls, [])

    def test_apply_only_accepts_the_listed_value(self):
        self.windows_default()
        for bad in ('1;6;10', '0;0', '0;0;0;0', '0,0,0', ' 0;0;0', 0, None, True, ('0', '0', '0'),
                    '0;0;1', ';;'):
            with self.subTest(value=bad):
                with self.assertRaises(at.AdvancedTweakError):
                    self.adapter.apply('mouse_precision', bad)
        self.assertEqual(self.writes(), [])
        self.adapter.apply('mouse_precision', '0;0;0')
        self.assertEqual(self.values(), (('0', SZ),) * 3)
        # Só os 3 valores da lista: a sensibilidade (outro valor da mesma chave) não muda.
        self.assertEqual(self.reg.get(MOUSE, 'MouseSensitivity'), ('10', SZ))
        names = {c[2] for c in self.reg.calls if c[0] == 'SetValueEx'}
        self.assertEqual(names, set(NAMES))
        self.assertTrue(all(c[3] == SZ for c in self.reg.calls if c[0] == 'SetValueEx'))

    def test_revert_only_accepts_texts_of_1_to_3_digits_or_absent(self):
        self.windows_default()
        for bad in ('1;6', '1;6;10;0', '1;6;1000', 'a;6;10', '-1;6;10', '1;6;1٠', '1;6;²',
                    '1 ;6;10', None, 1, '1/6/10', '1;6;10\n'):
            with self.subTest(value=bad):
                with self.assertRaises(at.AdvancedTweakError):
                    self.adapter.revert('mouse_precision', bad)
        self.assertEqual(self.writes(), [])

    def test_only_hkcu_is_used(self):
        self.adapter.read('mouse_precision')
        self.adapter.apply('mouse_precision', '0;0;0')
        self.adapter.revert('mouse_precision', ';;')
        self.assertTrue(self.reg.calls)   # o FakeWinreg falha o teste se for fora de HKCU


class OtherTypeTests(Base):
    # Critério 2: outro tipo (DWORD, binário) ou texto fora do padrão = "o app não mexe".
    def test_other_type_or_text_out_of_pattern_is_not_touched(self):
        cases = ((FakeWinreg.REG_DWORD, 1), (FakeWinreg.REG_BINARY, b'\x01'),
                 (FakeWinreg.REG_QWORD, 1), (FakeWinreg.REG_EXPAND_SZ, '1'),
                 (SZ, ''), (SZ, '1000'), (SZ, 'abc'), (SZ, ' 1'), (SZ, '١'), (SZ, '1.0'))
        for kind, value in cases:
            for position in range(3):
                with self.subTest(kind=kind, value=value, position=position):
                    self.reg = FakeWinreg()
                    self.adapter = at.AdvancedRegistryAdapter(registry=self.reg)
                    self.windows_default()
                    self.reg.put(MOUSE, NAMES[position], value, kind)
                    before = self.values()
                    with self.assertRaises(at.NotTextError):
                        self.adapter.read('mouse_precision')
                    for call in (lambda: self.adapter.apply('mouse_precision', '0;0;0'),
                                 lambda: self.adapter.revert('mouse_precision', '1;6;10'),
                                 lambda: self.adapter.revert('mouse_precision', ';;')):
                        with self.assertRaises(at.NotTextError):
                            call()
                    self.assertEqual(self.values(), before)
                    self.assertFalse([c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue')])
                    states = at.read_states(self.adapter)
                    self.assertEqual(states, [{'id': 'mouse_precision', 'state': 'other_type',
                                               'changes': []}])
                    self.assertIn('o app não mexe', '\n'.join(at.state_lines(states)))

    def test_unreadable_is_not_touched(self):
        self.windows_default()
        self.reg.fail_read.add('MouseThreshold1')
        states = at.read_states(self.adapter)
        self.assertEqual(states[0]['state'], 'unreadable')
        self.assertEqual(states[0]['changes'], [])
        text = '\n'.join(at.state_lines(states))
        self.assertIn('Não foi possível ler', text)
        self.assertNotIn('Fulano', text)


class ApplyAndUndoTests(Base):
    # Critério 3: aplicar e desfazer volta exatamente os 3 textos antigos.
    def test_read_combines_the_three_old_texts(self):
        self.windows_default()
        self.assertEqual(self.adapter.read('mouse_precision'), '1;6;10')
        self.assertTrue(cj.is_simple_value('1;6;10'))
        self.assertEqual(at.read_states(self.adapter),
                         [{'id': 'mouse_precision', 'state': 'not_applied',
                           'changes': [{'kind': at.ADVANCED_KIND, 'key': 'mouse_precision',
                                        'after': '0;0;0'}]}])

    def test_absent_key_or_values_read_as_empty_slots(self):
        self.assertEqual(self.adapter.read('mouse_precision'), ';;')
        self.reg.put(MOUSE, 'MouseThreshold1', '6', SZ)
        self.assertEqual(self.adapter.read('mouse_precision'), ';6;')
        self.assertEqual(self.writes(), [])

    def test_already_applied(self):
        for name in NAMES:
            self.reg.put(MOUSE, name, '0', SZ)
        states = at.read_states(self.adapter)
        self.assertEqual(states, [{'id': 'mouse_precision', 'state': 'applied', 'changes': []}])
        self.assertIn('já aplicado', '\n'.join(at.state_lines(states)))

    def test_apply_and_undo_through_the_journal_bring_back_the_exact_old_texts(self):
        for old in (('1', '6', '10'), ('2', '4', '12'), ('0', '6', '10'), ('1', '0', '0')):
            with self.subTest(old=old):
                self.reg = FakeWinreg()
                self.adapter = at.AdvancedRegistryAdapter(registry=self.reg)
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                self.tmp = Path(tmp.name)
                for name, value in zip(NAMES, old):
                    self.reg.put(MOUSE, name, value, SZ)
                journal = self.journal()
                changes = at.read_states(self.adapter)[0]['changes']
                ids = journal.apply_batch(changes)
                self.assertEqual(len(ids), 1)
                self.assertEqual(self.values(), (('0', SZ),) * 3)
                entry = journal.entries()[0]
                self.assertEqual((entry['before'], entry['after'], entry['status']),
                                 (';'.join(old), '0;0;0', 'applied'))
                self.assertEqual(journal.summary_lines()[0], '1. Aceleração do mouse: aplicada.')
                done, pending, reason = journal.undo_all()
                self.assertEqual((len(done), pending, reason), (1, [], ''))
                self.assertEqual(self.values(), tuple((v, SZ) for v in old))

    def test_value_absent_before_is_deleted_on_undo_and_the_key_stays(self):
        self.reg.put(MOUSE, 'MouseSpeed', '1', SZ)
        self.reg.put(MOUSE, 'MouseSensitivity', '10', SZ)
        journal = self.journal()
        journal.apply_batch(at.read_states(self.adapter)[0]['changes'])
        self.assertEqual(journal.entries()[0]['before'], '1;;')
        self.assertEqual(self.values(), (('0', SZ),) * 3)
        journal.undo_all()
        self.assertEqual(self.values(), (('1', SZ), None, None))
        self.assertEqual(self.reg.get(MOUSE, 'MouseSensitivity'), ('10', SZ))
        self.assertIn(MOUSE.lower(), self.reg.keys)
        deletes = [c[2] for c in self.reg.calls if c[0] == 'DeleteValue']
        self.assertEqual(deletes, ['MouseThreshold1', 'MouseThreshold2'])

    def test_key_created_by_the_app_stays_after_undo(self):
        journal = self.journal()
        journal.apply_batch(at.read_states(self.adapter)[0]['changes'])
        self.assertEqual(journal.entries()[0]['before'], ';;')
        journal.undo_all()
        self.assertEqual(self.values(), (None, None, None))
        self.assertIn(MOUSE.lower(), self.reg.keys)   # nunca apaga a chave (DeleteKey falha o teste)

    def test_revert_with_only_deletes_and_missing_key_does_nothing(self):
        self.adapter.revert('mouse_precision', ';;')
        self.assertEqual(self.writes(), [])

    def test_recheck_sees_undo_done_outside(self):
        self.windows_default()
        journal = self.journal()
        journal.apply_batch(at.read_states(self.adapter)[0]['changes'])
        for name, value in zip(NAMES, ('1', '6', '10')):
            self.reg.put(MOUSE, name, value, SZ)   # desfeito no Painel de Controle
        result = journal.recheck()
        self.assertEqual(len(result['changed']), 1)
        self.assertEqual(journal.entries()[0]['status'], 'reverted')


class PartialFailureTests(Base):
    # Critério 4: falha no 2º ou 3º valor volta o que já tinha sido gravado.
    def test_failure_on_second_or_third_value_rolls_back_inside_the_adapter(self):
        for failing in ('MouseThreshold1', 'MouseThreshold2'):
            with self.subTest(failing=failing):
                self.reg = FakeWinreg()
                self.adapter = at.AdvancedRegistryAdapter(registry=self.reg)
                self.windows_default()
                self.reg.fail_set.add(failing)
                with self.assertRaises(at.AdvancedTweakError) as raised:
                    self.adapter.apply('mouse_precision', '0;0;0')
                self.assertNotIn('Fulano', str(raised.exception))
                self.assertEqual(self.values(), (('1', SZ), ('6', SZ), ('10', SZ)))

    def test_failure_rolls_back_values_that_were_absent(self):
        self.reg.put(MOUSE, 'MouseSpeed', '1', SZ)
        self.reg.fail_set.add('MouseThreshold2')
        with self.assertRaises(at.AdvancedTweakError):
            self.adapter.apply('mouse_precision', '0;0;0')
        self.assertEqual(self.values(), (('1', SZ), None, None))

    def test_failure_in_revert_keeps_the_applied_values_together(self):
        self.windows_default()
        self.adapter.apply('mouse_precision', '0;0;0')
        self.reg.fail_set.add('MouseThreshold2')
        with self.assertRaises(at.AdvancedTweakError):
            self.adapter.revert('mouse_precision', '1;6;10')
        self.assertEqual(self.values(), (('0', SZ),) * 3)

    def test_journal_marks_failed_and_nothing_stays_changed(self):
        self.windows_default()
        self.reg.fail_set.add('MouseThreshold2')
        journal = self.journal()
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch(at.read_states(self.adapter)[0]['changes'])
        self.assertEqual(journal.entries()[0]['status'], 'failed')
        self.assertEqual(self.values(), (('1', SZ), ('6', SZ), ('10', SZ)))

    def test_restore_point_refused_writes_nothing(self):
        # Critério 7 (no motor): ponto de restauração recusado = nada gravado.
        self.windows_default()
        self.restore_ok = False
        journal = self.journal()
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch(at.read_states(self.adapter)[0]['changes'])
        self.assertEqual(self.writes(), [])
        self.assertEqual(journal.entries(), [])


class TextTests(Base):
    def test_confirmation_shows_what_downside_when_and_undo(self):
        tweak = at.TWEAKS_BY_ID['mouse_precision']
        text = at.confirmation_text(tweak)
        for part in (tweak.name, tweak.what, tweak.downside, tweak.when, 'Lado ruim',
                     'ponto de restauração', 'diário de alterações', 'Desfazer tudo',
                     at.CHANGES_TAB_NAME):
            self.assertIn(part, text)
        self.assertNotIn('\\', text)

    def test_state_lines_use_fixed_texts(self):
        lines = at.state_lines([{'id': 'mouse_precision', 'state': 'qualquer'}, {'id': 'outro'}])
        self.assertEqual(len(lines), 2)
        self.assertIn(at.STATE_TEXT['unreadable'], lines[1])


if __name__ == '__main__':
    unittest.main()
