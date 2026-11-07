"""FIX-M3-T5: valor ausente no registro = padrão efetivo do Windows.

No PC do Raphael (issue #207), sem os valores ``AutoGameModeEnabled`` e
``HistoricalCaptureEnabled`` o Windows mostra Modo de Jogo ligado e "Gravar o
que aconteceu" desligado. O app passa a ler o ausente como esse padrão: o
ajuste aparece como "já aplicado (padrão do Windows)" e não entra no lote; o
app nunca grava o valor padrão por cima do ausente.

Só registro falso em memória (``tests/fake_winreg.py``), ponto de restauração
falso e arquivos em TemporaryDirectory. Nenhum registro, PowerShell ou
subprocess de verdade.
"""
import dataclasses
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

import change_journal as cj  # noqa: E402
import safe_tweaks as st  # noqa: E402
from fake_winreg import FakeWinreg  # noqa: E402

GAMEBAR = r'Software\Microsoft\GameBar'
DVR = r'Software\Microsoft\Windows\CurrentVersion\GameDVR'
THEMES = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
WRITES = ('SetValueEx', 'DeleteValue', 'CreateKeyEx')


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
        self.adapter = st.RegistryTweakAdapter(registry=self.reg)
        self.restore_calls = []

    def restore_point(self, description):
        self.restore_calls.append(description)
        return True

    def journal(self):
        return cj.ChangeJournal(self.tmp / 'diario.json', {st.TWEAK_KIND: self.adapter},
                                self.restore_point)

    def states(self):
        return {s['id']: s for s in st.read_states(self.adapter)}

    def writes(self):
        return [c for c in self.reg.calls if c[0] in WRITES]


class DefaultsTableTests(unittest.TestCase):
    def test_absent_defaults_are_the_ones_confirmed_on_windows(self):
        self.assertEqual(st.TWEAK_VALUES['game_mode'].absent_default, 1)
        self.assertEqual(st.TWEAK_VALUES['historical_capture'].absent_default, 0)
        # Transparência: padrão não confirmado no Windows real = desconhecido.
        self.assertIsNone(st.TWEAK_VALUES['transparency'].absent_default)

    def test_default_of_new_registry_value_is_unknown(self):
        value = st.RegistryValue('x', r'Software\X', 'X', 1, 'X')
        self.assertIsNone(value.absent_default)


class AbsentReadsAsDefaultTests(Base):
    def test_empty_registry_shows_game_mode_and_capture_as_windows_default(self):
        states = self.states()
        for tweak_id in ('game_mode', 'game_bar_capture'):
            self.assertEqual(states[tweak_id]['state'], 'applied')
            self.assertTrue(states[tweak_id]['by_default'])
            self.assertEqual(states[tweak_id]['changes'], [])
        self.assertEqual(states['transparency']['state'], 'not_applied')
        self.assertFalse(states['transparency'].get('by_default', False))
        listed = list(states.values())
        self.assertEqual([t.id for t in st.pending_tweaks(listed)], ['transparency'])
        self.assertEqual([c['key'] for c in st.pending_changes(listed)], ['transparency'])
        self.assertEqual(self.writes(), [])

    def test_state_lines_say_windows_default_and_app_writes_nothing(self):
        text = '\n'.join(st.state_lines(st.read_states(self.adapter)))
        self.assertIn('• Modo de Jogo ligado: já aplicado (padrão do Windows; o app não grava nada).',
                      text)
        self.assertIn('• Gravação em segundo plano do Xbox Game Bar desligada: '
                      + st.STATE_TEXT['applied_default'], text)
        self.assertIn('• Efeitos de transparência desligados: ainda não aplicado.', text)
        self.assertEqual(st.STATE_TEXT['applied_default'],
                         'já aplicado (padrão do Windows; o app não grava nada).')

    def test_explicit_values_opposite_to_desired_are_not_applied(self):
        self.reg.put(GAMEBAR, 'AutoGameModeEnabled', 0)
        self.reg.put(DVR, 'HistoricalCaptureEnabled', 1)
        states = self.states()
        for tweak_id in ('game_mode', 'game_bar_capture'):
            self.assertEqual(states[tweak_id]['state'], 'not_applied')
            self.assertFalse(states[tweak_id].get('by_default', False))
        self.assertEqual([c['key'] for c in st.pending_changes(list(states.values()))],
                         ['game_mode', 'historical_capture', 'transparency'])

    def test_explicit_desired_value_is_applied_but_not_by_default(self):
        self.reg.put(GAMEBAR, 'AutoGameModeEnabled', 1)
        state = self.states()['game_mode']
        self.assertEqual(state['state'], 'applied')
        self.assertFalse(state.get('by_default', False))
        self.assertIn('• Modo de Jogo ligado: já aplicado.', st.state_lines([state]))

    def test_unknown_default_keeps_absent_as_not_applied(self):
        unknown = dataclasses.replace(st.TWEAK_VALUES['game_mode'], absent_default=None)
        tweak = dataclasses.replace(st.TWEAKS_BY_ID['game_mode'], values=(unknown,))
        with mock.patch.object(st, 'SAFE_TWEAKS', (tweak,)):
            states = st.read_states(self.adapter)
        self.assertEqual(states[0]['state'], 'not_applied')
        self.assertFalse(states[0].get('by_default', False))
        self.assertEqual([c['key'] for c in states[0]['changes']], ['game_mode'])

    def test_other_type_or_unreadable_still_left_out(self):
        self.reg.put(GAMEBAR, 'AutoGameModeEnabled', '1', FakeWinreg.REG_SZ)
        self.reg.put(DVR, 'HistoricalCaptureEnabled', 0)
        self.reg.fail_read.add('HistoricalCaptureEnabled')
        states = self.states()
        self.assertEqual(states['game_mode']['state'], 'other_type')
        self.assertEqual(states['game_bar_capture']['state'], 'unreadable')
        for tweak_id in ('game_mode', 'game_bar_capture'):
            self.assertEqual(states[tweak_id]['changes'], [])
            self.assertFalse(states[tweak_id].get('by_default', False))
        self.assertEqual([c['key'] for c in st.pending_changes(list(states.values()))],
                         ['transparency'])


class QuestionAndBatchTests(Base):
    def test_question_with_empty_registry_lists_only_transparency(self):
        tweaks = st.pending_tweaks(st.read_states(self.adapter))
        text = st.confirmation_text(tweaks)
        self.assertIn('Aplicar 1 ajuste(s)', text)
        self.assertIn(st.TWEAKS_BY_ID['transparency'].name, text)
        self.assertNotIn(st.TWEAKS_BY_ID['game_mode'].name, text)
        self.assertNotIn(st.TWEAKS_BY_ID['game_bar_capture'].name, text)

    def test_apply_from_empty_registry_never_writes_the_default_values(self):
        journal = self.journal()
        journal.apply_batch(st.pending_changes(st.read_states(self.adapter)))
        self.assertIsNone(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'))
        self.assertIsNone(self.reg.get(DVR, 'HistoricalCaptureEnabled'))
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (0, FakeWinreg.REG_DWORD))
        names = {c[2] for c in self.reg.calls if c[0] == 'SetValueEx'}
        self.assertEqual(names, {'EnableTransparency'})
        self.assertEqual([e['key'] for e in journal.entries()], ['transparency'])

    def test_apply_and_undo_from_absent_records_absent_and_deletes_only_the_value(self):
        journal = self.journal()
        journal.apply_batch(st.pending_changes(st.read_states(self.adapter)))
        entry = journal.entries()[0]
        self.assertIs(entry['before'], st.ABSENT)
        done, pending, reason = journal.undo_all()
        self.assertEqual((len(done), pending, reason), (1, [], ''))
        self.assertIsNone(self.reg.get(THEMES, 'EnableTransparency'))
        self.assertIn(THEMES.lower(), self.reg.keys)   # a chave nunca é apagada
        deleted = [c[2] for c in self.reg.calls if c[0] == 'DeleteValue']
        self.assertEqual(deleted, ['EnableTransparency'])
        # De volta ao "ausente": os padrões continuam valendo e a transparência pendente.
        states = self.states()
        self.assertTrue(states['game_mode']['by_default'])
        self.assertEqual(states['transparency']['state'], 'not_applied')

    def test_explicit_batch_from_absent_still_undoes_to_absent(self):
        # Diário antigo (antes deste FIX) pode ter gravado o Modo de Jogo saindo do ausente.
        journal = self.journal()
        journal.apply_batch([{'kind': st.TWEAK_KIND, 'key': 'game_mode', 'after': 1}])
        self.assertIs(journal.entries()[0]['before'], st.ABSENT)
        done, pending, reason = journal.undo_all()
        self.assertEqual((len(done), pending, reason), (1, [], ''))
        self.assertIsNone(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'))
        self.assertIn(GAMEBAR.lower(), self.reg.keys)

    def test_all_three_already_set_or_default_writes_nothing(self):
        self.reg.put(THEMES, 'EnableTransparency', 0)
        states = st.read_states(self.adapter)
        self.assertTrue(all(s['state'] == 'applied' for s in states))
        self.assertEqual(st.pending_changes(states), [])
        self.assertEqual(st.pending_tweaks(states), [])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.restore_calls, [])


if __name__ == '__main__':
    unittest.main()
