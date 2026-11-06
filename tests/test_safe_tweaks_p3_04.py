"""P3-04: ajustes seguros com 1 clique (lista fechada, HKCU, DWORD, pelo diário).

Só registro falso em memória (``tests/fake_winreg.py``), ponto de restauração
falso e arquivos em TemporaryDirectory. Nenhum registro, PowerShell ou
subprocess de verdade.
"""
import ast
import json
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
import session_owner as so  # noqa: E402
from fake_winreg import FakeWinreg  # noqa: E402

GAMEBAR = r'Software\Microsoft\GameBar'
DVR = r'Software\Microsoft\Windows\CurrentVersion\GameDVR'
THEMES = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'


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


class ClosedListTests(Base):
    def test_list_is_exactly_the_three_tweaks_three_values(self):
        self.assertEqual([t.id for t in st.SAFE_TWEAKS], ['game_mode', 'game_bar_capture', 'transparency'])
        values = [(v.path, v.name, v.desired) for t in st.SAFE_TWEAKS for v in t.values]
        self.assertEqual(values, [
            (GAMEBAR, 'AutoGameModeEnabled', 1),
            (DVR, 'HistoricalCaptureEnabled', 0),
            (THEMES, 'EnableTransparency', 0),
        ])
        self.assertEqual(set(st.TWEAK_VALUES), {'game_mode', 'historical_capture', 'transparency'})
        self.assertEqual(set(st.TWEAK_VALUES), {v.key for t in st.SAFE_TWEAKS for v in t.values})
        self.assertIsInstance(st.SAFE_TWEAKS, tuple)

    def test_each_tweak_has_simple_portuguese_texts_and_valid_journal_keys(self):
        for tweak in st.SAFE_TWEAKS:
            for text in (tweak.name, tweak.what, tweak.when):
                self.assertTrue(text.strip())
                self.assertNotIn('\\', text)
                self.assertNotIn('HK', text)
            for value in tweak.values:
                self.assertTrue(cj._valid_key(value.key))
                self.assertTrue(value.label and '\\' not in value.label)
        self.assertIn('na hora', st.TWEAKS_BY_ID['transparency'].when)
        self.assertIn('jogo', st.TWEAKS_BY_ID['game_bar_capture'].when)

    def test_game_bar_only_changes_what_the_name_promises(self):
        # Escolha do coordenador: só "Gravar o que aconteceu"; print e gravar na hora ficam como estavam.
        tweak = st.TWEAKS_BY_ID['game_bar_capture']
        self.assertEqual([v.name for v in tweak.values], ['HistoricalCaptureEnabled'])
        self.assertIn('Gravar o que aconteceu', tweak.what)
        self.assertIn('Tirar print e gravar na hora pelo Game Bar continuam como estavam', tweak.what)
        self.assertNotIn('continuam funcionando', tweak.what)
        self.assertIn('mesma opção que existe nas Configurações do Windows', tweak.what)
        source = (ROOT / 'safe_tweaks.py').read_text(encoding='utf-8')
        for gone in ('GameDVR_Enabled', 'AppCaptureEnabled', 'GameConfigStore', 'documentad'):
            self.assertNotIn(gone, source)
        for key in ('game_dvr', 'app_capture'):
            with self.assertRaises(st.TweakError):
                self.adapter.read(key)
        self.assertEqual(self.reg.calls, [])

    def test_nothing_about_hklm_defender_update_services_or_bios(self):
        source = (ROOT / 'safe_tweaks.py').read_text(encoding='utf-8')
        for forbidden in ('HKEY_LOCAL_MACHINE', 'HKLM', 'Defender', 'WindowsUpdate', 'Windows Update',
                          'wuauserv', 'Policies', 'Services', 'DeleteKey', 'subprocess', 'powershell',
                          'BIOS'):
            self.assertNotIn(forbidden, source)
        for tweak in st.SAFE_TWEAKS:
            for value in tweak.values:
                self.assertFalse(value.path.lower().startswith(('software\\policies', 'system\\currentcontrolset')))
        tree = ast.parse(source)
        calls = {n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertNotIn('DeleteKey', calls)
        self.assertNotIn('DeleteKeyEx', calls)

    def test_key_outside_the_list_is_refused_without_touching_the_registry(self):
        for key in ('outro', 'game_mode ', 'GAME_MODE', '', None, 1,
                    r'Software\Microsoft\GameBar', 'HKLM.qualquer'):
            with self.subTest(key=key):
                for call in (lambda: self.adapter.read(key),
                             lambda: self.adapter.apply(key, 1),
                             lambda: self.adapter.revert(key, None)):
                    with self.assertRaises(st.TweakError):
                        call()
        self.assertEqual(self.reg.calls, [])

    def test_only_hkcu_is_used(self):
        self.adapter.read('game_mode')
        self.adapter.apply('game_mode', 1)
        self.adapter.revert('game_mode', None)
        self.assertTrue(self.reg.calls)   # o FakeWinreg falha o teste se for fora de HKCU

    def test_default_adapter_does_not_touch_winreg_on_construction(self):
        adapter = st.RegistryTweakAdapter()
        self.assertEqual(adapter.kind, st.TWEAK_KIND)
        with mock.patch.object(st, '_is_windows', return_value=False):
            with self.assertRaises(st.TweakError):
                adapter.read('game_mode')


class AdapterTests(Base):
    def test_read_absent_key_and_absent_value_is_the_marker(self):
        self.assertIs(self.adapter.read('game_mode'), st.ABSENT)
        self.reg.put(GAMEBAR, 'Outro', 5)
        self.assertIs(self.adapter.read('game_mode'), st.ABSENT)
        self.assertIsNone(st.ABSENT)   # valor simples aceito pelo diário

    def test_read_dword(self):
        self.reg.put(GAMEBAR, 'AutoGameModeEnabled', 0)
        self.assertEqual(self.adapter.read('game_mode'), 0)

    def test_other_type_is_refused_without_changing_anything(self):
        for kind, value in ((FakeWinreg.REG_SZ, '1'), (FakeWinreg.REG_QWORD, 1),
                            (FakeWinreg.REG_BINARY, b'\x01')):
            with self.subTest(kind=kind):
                self.reg.put(GAMEBAR, 'AutoGameModeEnabled', value, kind)
                with self.assertRaises(st.NotDwordError):
                    self.adapter.read('game_mode')
                for call in (lambda: self.adapter.apply('game_mode', 1),
                             lambda: self.adapter.revert('game_mode', 0),
                             lambda: self.adapter.revert('game_mode', None)):
                    with self.assertRaises(st.NotDwordError):
                        call()
                self.assertEqual(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'), (value, kind))
        self.assertFalse([c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue')])

    def test_apply_only_writes_the_listed_value(self):
        for bad in (0, 2, True, '1', 1.0, None):
            with self.subTest(value=bad):
                with self.assertRaises(st.TweakError):
                    self.adapter.apply('game_mode', bad)
        self.assertEqual(self.reg.calls, [])
        self.adapter.apply('game_mode', 1)
        self.assertEqual(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'), (1, FakeWinreg.REG_DWORD))

    def test_revert_to_old_dword_and_bad_values_refused(self):
        self.adapter.revert('transparency', 7)
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (7, FakeWinreg.REG_DWORD))
        for bad in (-1, 2 ** 32, True, 'x', 1.5):
            with self.subTest(value=bad):
                with self.assertRaises(st.TweakError):
                    self.adapter.revert('transparency', bad)
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (7, FakeWinreg.REG_DWORD))

    def test_revert_to_absent_deletes_only_that_value_never_the_key(self):
        self.reg.put(THEMES, 'EnableTransparency', 0)
        self.reg.put(THEMES, 'AppsUseLightTheme', 1)
        self.adapter.revert('transparency', st.ABSENT)
        self.assertIsNone(self.reg.get(THEMES, 'EnableTransparency'))
        self.assertEqual(self.reg.get(THEMES, 'AppsUseLightTheme'), (1, FakeWinreg.REG_DWORD))
        self.assertIn(THEMES.lower(), self.reg.keys)
        # Já ausente (ou chave ausente): nada a fazer, sem erro.
        self.adapter.revert('transparency', st.ABSENT)
        self.adapter.revert('game_mode', st.ABSENT)
        deletes = [c for c in self.reg.calls if c[0] == 'DeleteValue']
        self.assertEqual(deletes, [('DeleteValue', THEMES.lower(), 'EnableTransparency')])

    def test_labels_per_key(self):
        self.assertEqual(self.adapter.label_for('game_mode'), 'Modo de Jogo')
        self.assertEqual(self.adapter.label_for('transparency'), 'Efeitos de transparência')
        self.assertEqual(self.adapter.label_for('outro'), self.adapter.label)


class JournalFlowTests(Base):
    def all_changes(self):
        return st.pending_changes(st.read_states(self.adapter))

    def test_apply_undo_and_recheck_through_the_journal(self):
        self.reg.put(THEMES, 'EnableTransparency', 1)
        self.reg.put(DVR, 'HistoricalCaptureEnabled', 1)
        journal = self.journal()
        changes = self.all_changes()
        self.assertEqual([c['key'] for c in changes],
                         ['game_mode', 'historical_capture', 'transparency'])
        ids = journal.apply_batch(changes)
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(self.restore_calls), 1)
        self.assertEqual(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'), (1, FakeWinreg.REG_DWORD))
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (0, FakeWinreg.REG_DWORD))
        befores = {e['key']: e['before'] for e in journal.entries()}
        self.assertEqual(self.reg.get(DVR, 'HistoricalCaptureEnabled'), (0, FakeWinreg.REG_DWORD))
        self.assertEqual(befores, {'game_mode': None, 'historical_capture': 1, 'transparency': 1})
        self.assertTrue(all(s['state'] == 'applied' for s in st.read_states(self.adapter)))
        self.assertEqual(self.all_changes(), [])
        self.assertIn('1. Modo de Jogo: aplicada.', journal.summary_lines())
        # Conferir de novo: só lê, nada muda.
        writes = len([c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue')])
        result = journal.recheck()
        self.assertEqual(result['changed'], [])
        self.assertEqual(len([c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue')]), writes)
        done, pending, reason = journal.undo_all()
        self.assertEqual((len(done), pending, reason), (3, [], ''))
        self.assertIsNone(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'))
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (1, FakeWinreg.REG_DWORD))
        self.assertEqual(self.reg.get(DVR, 'HistoricalCaptureEnabled'), (1, FakeWinreg.REG_DWORD))
        # A chave criada pelo app continua lá (vazia): nunca apaga a chave.
        self.assertIn(GAMEBAR.lower(), self.reg.keys)
        saved = json.loads((self.tmp / 'diario.json').read_text(encoding='utf-8'))
        self.assertTrue(all(e['status'] == 'reverted' for e in saved['entries']))
        self.assertNotIn('\\', json.dumps(saved).replace('\\\\', ''))

    def test_recheck_sees_outside_undo(self):
        journal = self.journal()
        journal.apply_batch([{'kind': st.TWEAK_KIND, 'key': 'transparency', 'after': 0}])
        del self.reg.keys[THEMES.lower()]['EnableTransparency']
        result = journal.recheck()
        self.assertEqual([c[2] for c in result['changed']], ['reverted'])

    def test_undo_refused_when_changed_outside(self):
        journal = self.journal()
        ids = journal.apply_batch([{'kind': st.TWEAK_KIND, 'key': 'transparency', 'after': 0}])
        self.reg.put(THEMES, 'EnableTransparency', 1)
        ok, reason = journal.undo(ids[0])
        self.assertFalse(ok)
        self.assertEqual(reason, cj.MSG_CHANGED_OUTSIDE)
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (1, FakeWinreg.REG_DWORD))

    def test_failure_in_the_middle_rolls_back_what_was_applied(self):
        self.reg.put(DVR, 'HistoricalCaptureEnabled', 1)
        self.reg.fail_set.add('HistoricalCaptureEnabled')
        journal = self.journal()
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch(self.all_changes())
        self.assertIsNone(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'))
        self.assertEqual(self.reg.get(DVR, 'HistoricalCaptureEnabled'), (1, FakeWinreg.REG_DWORD))
        self.assertIsNone(self.reg.get(THEMES, 'EnableTransparency'))
        statuses = [e['status'] for e in journal.entries()]
        self.assertEqual(statuses, ['failed', 'failed'])

    def test_write_that_does_not_stick_is_not_confirmed(self):
        self.reg.ignore_set.add('EnableTransparency')
        journal = self.journal()
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch([{'kind': st.TWEAK_KIND, 'key': 'game_mode', 'after': 1},
                                 {'kind': st.TWEAK_KIND, 'key': 'transparency', 'after': 0}])
        self.assertIsNone(self.reg.get(GAMEBAR, 'AutoGameModeEnabled'))

    def test_no_restore_point_means_nothing_changes(self):
        journal = cj.ChangeJournal(self.tmp / 'diario.json', {st.TWEAK_KIND: self.adapter},
                                   lambda description: False)
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch(self.all_changes())
        self.assertFalse([c for c in self.reg.calls if c[0] in ('SetValueEx', 'DeleteValue', 'CreateKeyEx')])


class StatesTests(Base):
    def test_states_and_pending_skip_what_is_already_set(self):
        self.reg.put(GAMEBAR, 'AutoGameModeEnabled', 1)
        self.reg.put(THEMES, 'EnableTransparency', 1)
        states = {s['id']: s for s in st.read_states(self.adapter)}
        self.assertEqual(states['game_mode']['state'], 'applied')
        self.assertEqual(states['game_bar_capture']['state'], 'not_applied')
        self.assertEqual([c['key'] for c in states['game_bar_capture']['changes']], ['historical_capture'])
        self.assertEqual(states['transparency']['state'], 'not_applied')
        self.assertEqual([c['key'] for c in st.pending_changes(list(states.values()))],
                         ['historical_capture', 'transparency'])
        self.assertEqual([t.id for t in st.pending_tweaks(list(states.values()))],
                         ['game_bar_capture', 'transparency'])

    def test_other_type_or_unreadable_tweak_is_left_out_whole(self):
        self.reg.put(DVR, 'HistoricalCaptureEnabled', '0', FakeWinreg.REG_SZ)
        self.reg.put(THEMES, 'EnableTransparency', 1)
        self.reg.fail_read.add('EnableTransparency')
        states = {s['id']: s for s in st.read_states(self.adapter)}
        self.assertEqual(states['game_bar_capture']['state'], 'other_type')
        self.assertEqual(states['game_bar_capture']['changes'], [])
        self.assertEqual(states['transparency']['state'], 'unreadable')
        self.assertEqual([c['key'] for c in st.pending_changes(list(states.values()))], ['game_mode'])
        text = '\n'.join(st.state_lines(list(states.values())))
        self.assertIn('outro tipo', text)
        self.assertIn('Não foi possível ler', text)
        self.assertNotIn('Fulano', text)
        self.assertNotIn('\\', text)

    def test_confirmation_lists_changes_restore_point_journal_and_when(self):
        tweaks = list(st.SAFE_TWEAKS)
        text = st.confirmation_text(tweaks)
        for tweak in tweaks:
            self.assertIn(tweak.name, text)
            self.assertIn(tweak.when, text)
        self.assertIn('ponto de restauração', text)
        self.assertIn('diário de alterações', text)
        self.assertIn('Desfazer tudo', text)
        self.assertIn('7  Alterações feitas', text)
        # Só sugere medir antes (não obriga).
        self.assertIn('\nPara comparar, meça ANTES na aba 1 antes de aplicar.', text)
        self.assertNotIn('\\', text)
        lines = st.applied_lines(tweaks)
        self.assertTrue(any('na hora' in line for line in lines))


class UnknownKindTests(Base):
    """Ressalva 7: um diário com um tipo desconhecido continua sendo recusado."""

    def test_unknown_kind_is_refused_and_touches_nothing(self):
        journal = self.journal()
        journal.apply_batch([{'kind': st.TWEAK_KIND, 'key': 'transparency', 'after': 0}])
        path = self.tmp / 'diario.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['entries'][0]['kind'] = 'registro_livre'
        path.write_text(json.dumps(data), encoding='utf-8')
        calls = len(self.reg.calls)
        journal = self.journal()
        ok, reason = journal.undo(journal.entries()[0]['id'])
        self.assertFalse(ok)
        self.assertIn('não sabe', reason)
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch([{'kind': 'registro_livre', 'key': 'transparency', 'after': 0}])
        self.assertEqual(len(self.reg.calls), calls)
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (0, FakeWinreg.REG_DWORD))

    def test_old_key_outside_the_list_is_refused_and_writes_nothing(self):
        journal = self.journal()
        journal.apply_batch([{'kind': st.TWEAK_KIND, 'key': 'transparency', 'after': 0}])
        path = self.tmp / 'diario.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['entries'][0]['key'] = 'app_capture'   # chave que saiu da lista
        path.write_text(json.dumps(data), encoding='utf-8')
        journal = self.journal()
        calls = len(self.reg.calls)
        ok, _reason = journal.undo(journal.entries()[0]['id'])
        self.assertFalse(ok)
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch([{'kind': st.TWEAK_KIND, 'key': 'app_capture', 'after': 0}])
        self.assertFalse([c for c in self.reg.calls[calls:] if c[0] in ('SetValueEx', 'DeleteValue')])
        self.assertEqual(self.reg.get(THEMES, 'EnableTransparency'), (0, FakeWinreg.REG_DWORD))


class SessionOwnerTests(unittest.TestCase):
    """R-55: a consulta da conta é injetável; na dúvida, "não deu para saber"."""

    def test_probe_answers_pass_through(self):
        for answer in (so.SAME, so.OTHER, so.UNKNOWN):
            with self.subTest(answer=answer):
                self.assertEqual(so.session_owner(lambda: answer), answer)

    def test_error_or_strange_answer_is_unknown(self):
        def boom():
            raise OSError(5, r'Acesso negado C:\Users\Fulano')
        self.assertEqual(so.session_owner(boom), so.UNKNOWN)
        for strange in (True, None, 1, 'mesma', 'Mesma conta', b'mesma conta'):
            with self.subTest(answer=strange):
                self.assertEqual(so.session_owner(lambda: strange), so.UNKNOWN)

    def test_outside_windows_is_unknown_without_calling_windows(self):
        with mock.patch.object(so.sys, 'platform', 'linux'), \
                mock.patch.object(so, '_windows_probe', side_effect=AssertionError('chamou o Windows')):
            self.assertEqual(so.session_owner(), so.UNKNOWN)

    def test_windows_failure_is_unknown(self):
        with mock.patch.object(so.sys, 'platform', 'win32'), \
                mock.patch.object(so, '_windows_probe', side_effect=OSError('falhou')):
            self.assertEqual(so.session_owner(), so.UNKNOWN)

    def test_windows_probe_only_reads(self):
        source = (ROOT / 'session_owner.py').read_text(encoding='utf-8')
        for needed in ('OpenProcessToken', 'GetTokenInformation', 'WTSQuerySessionInformationW',
                       'WTS_CURRENT_SESSION', 'LookupAccountNameW', 'EqualSid'):
            self.assertIn(needed, source)
        for forbidden in ('subprocess', 'winreg', 'SetToken', 'AdjustToken', 'ImpersonateLoggedOnUser',
                          'CreateProcess', 'ShellExecute', 'RunAs', 'os.system', 'open('):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
