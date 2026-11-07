"""FIX-M3-T3: reaproveitar o ponto de restauração que o próprio app criou nas últimas 24 h.

O Windows só cria um ponto novo a cada 24 horas. Agora o app anota no diário o
ponto que ele mesmo criou e, num lote seguinte, confere no Windows (sequência,
descrição fixa e hora) antes da pergunta e de novo antes de aplicar. Sem um
ponto assim, recusa como antes. O app nunca muda a frequência de pontos.

Tudo com Windows, administrador e relógio falsos, e arquivos em
TemporaryDirectory. Nenhum PowerShell, registro ou subprocess de verdade. Sem
Tk (ou sem tela) os testes de janela pulam.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import advanced_tweaks as at  # noqa: E402
import change_journal as cj  # noqa: E402
import optimization_engine as oe  # noqa: E402
import safe_tweaks as st  # noqa: E402
import session_owner as so  # noqa: E402
from fake_winreg import FakeWinreg  # noqa: E402

try:
    import tkinter as tk
    import optimization_ui as ou
    from tk_helpers import track_tk_root
except ImportError:  # Python sem Tk: os testes de tela pulam.
    tk = ou = track_tk_root = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))

GUID = '381b4222-f694-41f0-9685-ff5bb260df2e'
SZ = FakeWinreg.REG_SZ
MOUSE = r'Control Panel\Mouse'
MOUSE_NAMES = ('MouseSpeed', 'MouseThreshold1', 'MouseThreshold2')
WRITES = ('SetValueEx', 'DeleteValue', 'CreateKeyEx', 'DeleteKey', 'DeleteKeyEx')
T0 = datetime(2026, 11, 7, 19, 16, 0, tzinfo=timezone.utc)


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec='seconds')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NoRealCommands(unittest.TestCase):
    def setUp(self):
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('_run', '_ps'):
            patcher = mock.patch.object(oe, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)


class FakeWindowsPoints:
    """Windows falso: só responde à consulta de um ponto e à criação."""

    def __init__(self, sequence=12, created=T0, description=oe.RESTORE_POINT_DESCRIPTION):
        self.codes = []
        self.answer = {'Sequence': sequence, 'Description': description,
                       'Created': created.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.1234567Z')}
        self.fail = False

    def __call__(self, code, timeout=None):
        self.codes.append(code)
        if self.fail:
            raise oe.OptimizationError('falhou')
        if 'Get-ComputerRestorePoint' in code and 'Where-Object' in code:
            return self.answer
        raise AssertionError('consulta inesperada')


class FakeShell:
    """Criação do ponto: devolve a sequência antes e depois (como no teste da fatia 2)."""

    def __init__(self, sequence=(5, 6)):
        self.sequence = list(sequence)
        self.codes = []

    def __call__(self, code, timeout=None):
        self.codes.append(code)
        if code.startswith('Checkpoint-Computer'):
            return None
        return self.sequence.pop(0)


class FakeAdapter:
    label = 'Teste'

    def __init__(self):
        self.values = {'a': 0, 'b': 0}
        self.applied = []
        self.fail_read = False

    def read(self, key):
        if self.fail_read:
            raise OSError('sem leitura')
        return self.values[key]

    def apply(self, key, value):
        self.applied.append((key, value))
        self.values[key] = value

    def revert(self, key, value):
        self.values[key] = value


# ---------- motor: criar e confirmar ----------
class CreateAppRestorePointTests(NoRealCommands):
    def test_returns_the_new_sequence_only_when_it_increases(self):
        self.assertEqual(oe.create_app_restore_point(run=FakeShell((5, 6)), elevated=lambda: True),
                         {'sequence': 6})
        self.assertIsNone(oe.create_app_restore_point(run=FakeShell((7, 7)), elevated=lambda: True))
        self.assertIsNone(oe.create_app_restore_point(run=FakeShell(), elevated=lambda: False))

    def test_old_function_still_returns_true_or_false(self):
        self.assertIs(oe.create_restore_point(run=FakeShell((5, 6)), elevated=lambda: True), True)
        self.assertIs(oe.create_restore_point(run=FakeShell((7, 7)), elevated=lambda: True), False)

    def test_never_changes_the_windows_frequency(self):
        shell = FakeShell((5, 6))
        oe.create_app_restore_point(run=shell, elevated=lambda: True)
        code = ' '.join(shell.codes) + oe._restore_point_query(12)
        for forbidden in ('SystemRestorePointCreationFrequency', 'Set-ItemProperty', 'New-ItemProperty',
                          'reg ', 'Enable-ComputerRestore', 'Remove-'):
            self.assertNotIn(forbidden, code)
        source = (ROOT / 'optimization_engine.py').read_text(encoding='utf-8')
        self.assertNotIn('SystemRestorePointCreationFrequency', source)


class ConfirmAppRestorePointTests(NoRealCommands):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(oe, '_is_windows', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.windows = FakeWindowsPoints()
        self.record = {'sequence': 12, 'created': _iso(T0 + timedelta(minutes=1))}

    def confirm(self, record=None, now=None, elevated=True, run=None):
        return oe.confirm_app_restore_point(self.record if record is None else record,
                                            run=run or self.windows, elevated=lambda: elevated,
                                            now=now or T0 + timedelta(minutes=9))

    def test_confirmed_point_gives_the_windows_time(self):
        self.assertEqual(self.confirm(), T0.replace(microsecond=123456))
        self.assertEqual(len(self.windows.codes), 1)

    def test_query_only_has_digits_in_place_of_the_number(self):
        self.confirm()
        code = self.windows.codes[0]
        self.assertEqual(code, oe._restore_point_query(12))
        self.assertIn('$_.SequenceNumber -eq 12 }', code)
        self.assertEqual(re.findall(r'-eq (\S+) \}', code), ['12'])
        for forbidden in ('Checkpoint-Computer', 'Remove-', 'Set-', 'Enable-', 'Disable-'):
            self.assertNotIn(forbidden, code)
        self.assertIn('-eq 2147483648 }', oe._restore_point_query(2 ** 31))

    def test_each_doubt_gives_none(self):
        late = T0 + timedelta(hours=24, seconds=1)
        cases = {
            '24 h e 1 s depois': dict(now=late),
            'exatamente 24 h': dict(now=T0.replace(microsecond=123456) + timedelta(hours=24)),
            'data no futuro': dict(now=T0 - timedelta(seconds=1)),
            'relógio sem fuso': dict(now=(T0 + timedelta(minutes=9)).replace(tzinfo=None)),
            'sem administrador': dict(elevated=False),
        }
        for name, options in cases.items():
            with self.subTest(name):
                self.assertIsNone(self.confirm(**options))

    def test_windows_answer_that_does_not_match_gives_none(self):
        good = dict(self.windows.answer)
        bad_answers = {
            'outra descrição': dict(good, Description='Instalou um driver'),
            'descrição parecida': dict(good, Description=oe.RESTORE_POINT_DESCRIPTION + ' '),
            'outra sequência': dict(good, Sequence=13),
            'sequência em texto': dict(good, Sequence='12'),
            'sequência sim/não': dict(good, Sequence=True),
            'Created sem fuso': dict(good, Created='2026-11-07T19:16:00'),
            'Created estranho': dict(good, Created='ontem'),
            'Created número': dict(good, Created=5),
            'diferença de 16 min': dict(good, Created=_iso(T0 - timedelta(minutes=15, seconds=1))),
            'lista vazia': [],
            'nada (None)': None,
            'lista com o ponto': [good],
            'texto': 'ok',
        }
        for name, answer in bad_answers.items():
            with self.subTest(name):
                self.windows.answer = answer
                self.assertIsNone(self.confirm())

    def test_tolerance_of_fifteen_minutes(self):
        later = T0 + timedelta(minutes=30)
        self.windows.answer['Created'] = _iso(T0 + timedelta(minutes=16))   # registro: T0 + 1 min
        self.assertEqual(self.confirm(now=later), T0 + timedelta(minutes=16))
        self.windows.answer['Created'] = _iso(T0 + timedelta(minutes=16, seconds=1))
        self.assertIsNone(self.confirm(now=later))

    def test_exception_gives_none(self):
        self.windows.fail = True
        self.assertIsNone(self.confirm())

        def elevated_raises():
            raise OSError('sem resposta')
        self.assertIsNone(oe.confirm_app_restore_point(self.record, run=self.windows,
                                                       elevated=elevated_raises,
                                                       now=T0 + timedelta(minutes=9)))

    def test_bad_record_runs_nothing(self):
        bad_records = {
            'sequence sim/não': {'sequence': True, 'created': self.record['created']},
            'sequence texto': {'sequence': '12', 'created': self.record['created']},
            'sequence com comando': {'sequence': '1; Remove-Item x', 'created': self.record['created']},
            'sequence zero': {'sequence': 0, 'created': self.record['created']},
            'sequence negativa': {'sequence': -3, 'created': self.record['created']},
            'sequence grande': {'sequence': 2 ** 31 + 1, 'created': self.record['created']},
            'sequence fracionária': {'sequence': 12.0, 'created': self.record['created']},
            'created sem fuso': {'sequence': 12, 'created': '2026-11-07T19:17:00'},
            'sem created': {'sequence': 12},
            'não é dict': [12],
        }
        for name, record in bad_records.items():
            with self.subTest(name):
                self.assertIsNone(self.confirm(record=record))
        self.assertEqual(self.windows.codes, [])

    def test_outside_windows_runs_nothing(self):
        with mock.patch.object(oe, '_is_windows', return_value=False):
            self.assertIsNone(self.confirm())
        self.assertEqual(self.windows.codes, [])

    def test_without_admin_runs_nothing(self):
        self.assertIsNone(self.confirm(elevated=False))
        self.assertEqual(self.windows.codes, [])


# ---------- diário ----------
class JournalTests(NoRealCommands):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / 'diario.json'
        self.adapter = FakeAdapter()
        self.created = []
        self.checks = []
        self.create_answer = {'sequence': 12}
        self.confirm_answer = T0

    def create(self, description):
        self.created.append(description)
        return self.create_answer

    def confirm(self, record):
        self.checks.append(dict(record))
        if isinstance(self.confirm_answer, Exception):
            raise self.confirm_answer
        return self.confirm_answer

    def journal(self, confirm=True):
        return cj.ChangeJournal(self.path, {'teste': self.adapter}, self.create,
                                self.confirm if confirm else None)

    @staticmethod
    def change(key='a', after=1):
        return [{'kind': 'teste', 'key': key, 'after': after}]

    def data(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_created_point_is_noted_in_the_journal(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        self.journal().apply_batch(self.change())
        point = self.data()['restore_point']
        self.assertEqual(set(point), {'sequence', 'created'})
        self.assertEqual(point['sequence'], 12)
        created = datetime.fromisoformat(point['created'])
        self.assertEqual(created.utcoffset(), timedelta(0))
        self.assertLessEqual(before, created)
        self.assertEqual(self.data()['schema'], cj.SCHEMA)
        self.assertEqual(set(self.data()['entries'][0]), set(cj._ENTRY_FIELDS))

    def test_old_true_answer_does_not_note_a_point(self):
        self.create_answer = True
        journal = self.journal()
        journal.apply_batch(self.change())
        self.assertNotIn('restore_point', self.data())
        self.assertIsNone(journal.reusable_restore_point())
        self.assertEqual(self.checks, [])

    def test_bad_sequence_from_create_does_not_note_a_point(self):
        for answer in ({'sequence': True}, {'sequence': '12'}, {'sequence': 0}, {'outro': 3}):
            with self.subTest(answer=answer):
                self.path.unlink(missing_ok=True)
                self.create_answer = answer
                self.journal().apply_batch(self.change())
                self.assertNotIn('restore_point', self.data())

    def test_second_batch_nine_minutes_later_reuses_without_creating(self):
        with mock.patch.object(oe, '_is_windows', return_value=True):
            journal = self.journal()
            journal.apply_batch(self.change('a'))
            point = self.data()['restore_point']
            windows = FakeWindowsPoints(sequence=12, created=datetime.fromisoformat(point['created']))
            later = datetime.fromisoformat(point['created']) + timedelta(minutes=9)
            journal._confirm = lambda record: oe.confirm_app_restore_point(
                record, run=windows, elevated=lambda: True, now=later)
            reuse_at = journal.reusable_restore_point()
            self.assertIsNotNone(reuse_at)
            ids = journal.apply_batch(self.change('b'), reuse_restore_point=True)
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(self.created), 1)                 # só o 1º lote criou o ponto
        self.assertEqual(self.adapter.applied, [('a', 1), ('b', 1)])
        self.assertEqual(len(windows.codes), 2)                # antes da pergunta e antes de aplicar
        self.assertEqual(self.data()['restore_point'], point)  # o reaproveitamento não renova o prazo

    def test_point_gone_between_question_and_apply(self):
        journal = self.journal()
        journal.apply_batch(self.change('a'))
        self.assertEqual(journal.reusable_restore_point(), T0)   # antes da pergunta
        self.confirm_answer = None                               # o ponto sumiu
        digest = _sha(self.path)
        self.adapter.applied.clear()
        with self.assertRaises(cj.BatchRefused) as raised:
            journal.apply_batch(self.change('b'), reuse_restore_point=True)
        self.assertEqual(str(raised.exception), cj.MSG_REUSE_GONE)
        self.assertEqual(self.adapter.applied, [])
        self.assertEqual(len(self.created), 1)                   # não tentou criar outro
        self.assertEqual(_sha(self.path), digest)
        self.assertEqual(len(self.checks), 2)

    def test_reuse_without_a_noted_point_is_refused(self):
        self.create_answer = True
        journal = self.journal()
        journal.apply_batch(self.change('a'))
        with self.assertRaises(cj.BatchRefused) as raised:
            journal.apply_batch(self.change('b'), reuse_restore_point=True)
        self.assertEqual(str(raised.exception), cj.MSG_REUSE_GONE)
        self.assertEqual(len(self.created), 1)

    def test_without_confirm_function_never_reuses(self):
        journal = self.journal(confirm=False)
        journal.apply_batch(self.change('a'))
        self.assertIn('restore_point', self.data())
        self.assertIsNone(journal.reusable_restore_point())
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch(self.change('b'), reuse_restore_point=True)
        self.assertEqual(self.checks, [])

    def test_reuse_with_journal_changed_outside_refuses_before_checking(self):
        journal = self.journal()
        journal.apply_batch(self.change('a'))
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': []}), encoding='utf-8')
        digest = _sha(self.path)
        self.checks.clear()
        self.adapter.applied.clear()
        with self.assertRaises(cj.JournalError) as raised:
            journal.apply_batch(self.change('b'), reuse_restore_point=True)
        self.assertEqual(str(raised.exception), cj.MSG_OTHER_WINDOW)
        self.assertEqual(self.checks, [])          # não conferiu o ponto
        self.assertEqual(self.adapter.applied, [])
        self.assertEqual(len(self.created), 1)
        self.assertEqual(_sha(self.path), digest)

    def test_reuse_with_journal_turned_into_link_refuses_before_checking(self):
        journal = self.journal()
        journal.apply_batch(self.change('a'))
        real = self.tmp / 'copia.json'
        real.write_bytes(self.path.read_bytes())   # mesmo conteúdo: só o link é diferente
        self.path.unlink()
        try:
            os.symlink(real, self.path)
        except (OSError, NotImplementedError):
            self.skipTest('sem permissão para criar link')
        digest = _sha(real)
        self.checks.clear()
        self.adapter.applied.clear()
        with self.assertRaises(cj.JournalError) as raised:
            journal.apply_batch(self.change('b'), reuse_restore_point=True)
        self.assertIn('atalho (link)', str(raised.exception))
        self.assertEqual(self.checks, [])
        self.assertEqual(self.adapter.applied, [])
        self.assertEqual(len(self.created), 1)
        self.assertEqual(_sha(real), digest)
        self.assertTrue(os.path.islink(self.path))

    def test_confirm_must_be_callable(self):
        with self.assertRaises(cj.JournalError):
            cj.ChangeJournal(self.path, {'teste': self.adapter}, self.create, 'sim')

    def test_confirm_exception_or_strange_answer_gives_none(self):
        journal = self.journal()
        journal.apply_batch(self.change('a'))
        for answer in (OSError('x'), None, True, '2026-11-07T19:16:00+00:00',
                       T0.replace(tzinfo=None)):
            with self.subTest(answer=answer):
                self.confirm_answer = answer
                self.assertIsNone(journal.reusable_restore_point())

    def test_changed_journal_gives_none_without_asking_windows(self):
        journal = self.journal()
        journal.apply_batch(self.change('a'))
        other = self.journal()
        other.apply_batch(self.change('b'))      # outra janela gravou
        self.checks.clear()
        self.assertIsNone(journal.reusable_restore_point())
        self.assertEqual(self.checks, [])

    def test_refusal_does_not_create_and_keeps_message(self):
        self.create_answer = False
        journal = self.journal()
        with self.assertRaises(cj.BatchRefused) as raised:
            journal.apply_batch(self.change('a'))
        self.assertEqual(str(raised.exception), cj.MSG_RESTORE_POINT_FAILED)
        self.assertEqual(cj.MSG_RESTORE_POINT_FAILED,
                         'Não foi possível criar o ponto de restauração; nenhum ajuste foi aplicado.')
        self.assertFalse(self.path.exists())

    def test_point_not_saved_when_nothing_was_written(self):
        self.adapter.fail_read = True
        journal = self.journal()
        with self.assertRaises(cj.BatchRefused):
            journal.apply_batch(self.change('a'))
        self.assertFalse(self.path.exists())
        self.assertIsNone(journal.reusable_restore_point())
        self.assertEqual(self.checks, [])

    def test_invalid_point_in_the_file_is_ignored(self):
        bad_points = {
            'não é dict': [12],
            'chave a mais': {'sequence': 12, 'created': _iso(T0), 'path': 'C:'},
            'sem created': {'sequence': 12},
            'sequence sim/não': {'sequence': True, 'created': _iso(T0)},
            'sequence texto': {'sequence': '12', 'created': _iso(T0)},
            'sequence zero': {'sequence': 0, 'created': _iso(T0)},
            'sequence grande': {'sequence': 2 ** 31 + 1, 'created': _iso(T0)},
            'created sem fuso': {'sequence': 12, 'created': '2026-11-07T19:16:00'},
            'created número': {'sequence': 12, 'created': 5},
        }
        for name, point in bad_points.items():
            with self.subTest(name):
                self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': [],
                                                 'restore_point': point}), encoding='utf-8')
                self.checks.clear()
                journal = self.journal()
                self.assertEqual(journal.entries(), [])
                self.assertIsNone(journal.reusable_restore_point())
                self.assertEqual(self.checks, [])
                with self.assertRaises(cj.BatchRefused) as raised:
                    journal.apply_batch(self.change('a'), reuse_restore_point=True)
                self.assertEqual(str(raised.exception), cj.MSG_REUSE_GONE)
                journal.apply_batch(self.change('a'))           # o diário continua usável
                self.assertEqual(self.data()['restore_point']['sequence'], 12)

    def test_valid_point_in_the_file_is_read(self):
        point = {'sequence': 2 ** 31, 'created': _iso(T0)}
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': [],
                                         'restore_point': point}), encoding='utf-8')
        journal = self.journal()
        self.assertEqual(journal.reusable_restore_point(), T0)
        self.assertEqual(self.checks, [point])

    def test_old_file_without_the_field_opens(self):
        self.path.write_text(json.dumps({'schema': cj.SCHEMA, 'entries': []}), encoding='utf-8')
        journal = self.journal()
        self.assertEqual(journal.entries(), [])
        self.assertIsNone(journal.reusable_restore_point())
        self.create_answer = True
        journal.apply_batch(self.change('a'))
        self.assertEqual(set(self.data()), {'schema', 'entries'})


# ---------- textos ----------
class TextTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 7, 18, 0).astimezone()

    def test_when_today_and_yesterday(self):
        today = datetime(2026, 11, 7, 16, 16).astimezone()
        yesterday = datetime(2026, 11, 6, 20, 5).astimezone()
        self.assertEqual(st.restore_point_when(today, self.now), 'hoje às 16:16')
        self.assertEqual(st.restore_point_when(yesterday, self.now), 'ontem às 20:05')
        self.assertEqual(st.restore_point_when(today.astimezone(timezone.utc), self.now),
                         'hoje às 16:16')
        self.assertIs(at.restore_point_when, st.restore_point_when)

    def test_safe_question_mentions_the_point(self):
        tweaks = list(st.SAFE_TWEAKS)
        old = st.confirmation_text(tweaks)
        self.assertIn('Antes, o app cria um ponto de restauração do Windows', old)
        self.assertEqual(st.confirmation_text(tweaks, reuse_at=None, now=self.now), old)
        text = st.confirmation_text(tweaks, reuse_at=datetime(2026, 11, 7, 16, 16).astimezone(),
                                    now=self.now)
        self.assertIn('O app vai usar o ponto de restauração que ele mesmo criou hoje às 16:16 '
                      '(o Windows só cria um ponto novo a cada 24 horas) e anota tudo no diário '
                      'de alterações.', text)
        self.assertNotIn('Antes, o app cria', text)
        self.assertEqual(text, old.replace(
            'Antes, o app cria um ponto de restauração do Windows e anota tudo no diário de '
            'alterações.', 'O app vai usar o ponto de restauração que ele mesmo criou hoje às '
            '16:16 (o Windows só cria um ponto novo a cada 24 horas) e anota tudo no diário de '
            'alterações. Voltar a esse ponto desfaz também o que foi feito depois dele.'))
        self.assertNotIn('desfaz também', old)
        for forbidden in ('\\', 'C:', 'HK'):
            self.assertNotIn(forbidden, text)

    def test_advanced_question_mentions_the_point(self):
        tweak = at.TWEAKS_BY_ID['mouse_precision']
        old = at.confirmation_text(tweak)
        self.assertIn('Antes, o app cria um ponto de restauração do Windows', old)
        self.assertEqual(at.confirmation_text(tweak, reuse_at=None, now=self.now), old)
        text = at.confirmation_text(tweak, reuse_at=datetime(2026, 11, 6, 20, 5).astimezone(),
                                    now=self.now)
        self.assertIn('O app vai usar o ponto de restauração que ele mesmo criou ontem às 20:05 '
                      '(o Windows só cria um ponto novo a cada 24 horas)', text)
        self.assertIn('Voltar a esse ponto desfaz também o que foi feito depois dele.', text)
        self.assertNotIn('Antes, o app cria', text)
        for forbidden in ('\\', 'C:', 'HK'):
            self.assertNotIn(forbidden, text)


class IntroAndManualTextTests(unittest.TestCase):
    """R-72: introdução, ajuda e manual descrevem o mesmo passo da pergunta."""
    NEW = 'usa o que o próprio app criou nas últimas 24 horas'

    def test_intro_and_help_texts_of_tabs_8_and_9(self):
        if ou is None:
            self.skipTest('sem Tk')
        self.assertIn('antes, cria um ponto de restauração ou ' + self.NEW, ou.TWEAKS_INTRO_TEXT)
        self.assertIn('o app cria antes um ponto de restauração ou ' + self.NEW, ou.ADVANCED_INTRO_TEXT)
        self.assertIn('(ou confere o que o próprio app criou nas últimas 24 horas)',
                      ou.TWEAKS_ADMIN_TEXT)
        self.assertIn('O app só reaproveita um ponto criado por ele mesmo nas últimas 24 horas.',
                      ou.POWER_RESTORE_POINT_HELP)
        for text in (ou.TWEAKS_INTRO_TEXT, ou.ADVANCED_INTRO_TEXT):
            self.assertNotIn('cria um ponto de restauração e anota', text)
            self.assertNotIn('cria antes um ponto de restauração e anota', text)

    def test_manual_describes_the_reuse(self):
        manual = ' '.join((ROOT / 'docs' / 'MANUAL.md').read_text(encoding='utf-8').split())
        self.assertIn('o app cria um ponto de restauração do Windows ou ' + self.NEW, manual)
        self.assertIn('e cria um ponto de restauração ou ' + self.NEW + ' (a pergunta diz qual)',
                      manual)
        self.assertIn('Voltar a esse ponto desfaz também o que foi feito depois dele.', manual)
        self.assertNotIn('o app cria um ponto de restauração do Windows, e isso exige', manual)
        self.assertNotIn('pergunta antes e cria um ponto de restauração.', manual)


# ---------- tela ----------
class FakePower:
    kind = oe.POWER_KIND
    label = 'Plano de energia'

    def available(self):
        return [{'guid': GUID, 'name': 'Equilibrado', 'active': True}]

    def read(self, key):
        return GUID

    def apply(self, key, value):
        raise AssertionError('plano de energia não faz parte deste teste')

    revert = apply


class SourceTests(unittest.TestCase):
    def test_read_only_button_does_not_check_the_point(self):
        import ast
        tree = ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))
        functions = {n.name: ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for name in ('refresh_tweaks', 'refresh_advanced', '_checked_read_tweaks_work',
                     '_checked_read_advanced_work'):
            self.assertNotIn('reusable_restore_point', functions[name])
        self.assertIn('journal.reusable_restore_point()', functions['_reuse_at_for_apply'])
        for name, key in (('_checked_read_tweaks_for_apply_work', "'tweaks'"),
                          ('_checked_read_advanced_for_apply_work', "'advanced'")):
            code = functions[name]
            # Só com a mesma conta e a leitura ok, e depois da leitura.
            self.assertIn('session_owner.SAME', code)
            self.assertIn(f'outcome.get({key}) is not None', code)
            self.assertLess(code.index('_read_'), code.index('self._reuse_at_for_apply()'))
        for name in ('_tweaks_ready', '_advanced_ready'):
            self.assertIn('reuse_restore_point=reuse_at is not None', functions[name])
        self.assertIn('self._run_power_job(self._checked_read_tweaks_for_apply_work',
                      functions['apply_safe_tweaks'])
        self.assertIn('self._checked_read_advanced_for_apply_work', functions['apply_advanced'])


@unittest.skipIf(NO_DISPLAY, 'sem Tk ou sem tela')
class GuiTests(NoRealCommands):
    def setUp(self):
        super().setUp()
        self.reg = FakeWinreg()
        self.machine_reg = FakeWinreg(hives=('HKLM',))
        for name, value in zip(MOUSE_NAMES, ('1', '6', '10')):
            self.reg.put(MOUSE, name, value, SZ)
        self.restore_ok = False
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
            self.root, app_dir=self.tmp, state_dir=self.tmp, power_adapter=FakePower(),
            tweak_adapter=st.RegistryTweakAdapter(registry=self.reg),
            advanced_adapter=at.AdvancedRegistryAdapter(registry=self.reg),
            machine_adapter=at.MachineDwordAdapter(registry=self.machine_reg),
            restore_point=self._restore_point, restore_point_check=self._check,
            elevated_probe=lambda: True, session_owner_probe=lambda: so.SAME,
            ask=self._ask, show=lambda *a: self.shown.append(a))
        self.panel.pack()
        self.settle()
        self.addCleanup(self._join)  # R-29: roda antes da limpeza da pasta.

    def _restore_point(self, description):
        self.restore_calls.append(description)
        return self.restore_ok

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

    def writes(self):
        return [c for c in self.reg.calls + self.machine_reg.calls if c[0] in WRITES]

    def run_tab(self, tab):
        if tab == 8:
            self.panel.apply_safe_tweaks()
        else:
            self.panel.apply_advanced('mouse_precision')
        self.settle()

    def status(self, tab):
        return (self.panel.tweaks_status if tab == 8 else self.panel.advanced_status).get()

    def test_confirmed_point_is_named_in_the_question_and_used(self):
        for tab in (8, 9):
            with self.subTest(tab=tab):
                moment = datetime.now(timezone.utc) - timedelta(minutes=9)
                self.check_answers = [moment, moment]
                self.checks.clear()
                self.run_tab(tab)
                when = st.restore_point_when(moment, datetime.now(timezone.utc))
                self.assertIn('O app vai usar o ponto de restauração que ele mesmo criou ' + when,
                              self.asked[-1][1])
                self.assertEqual(self.restore_calls, [])
                self.assertEqual(len(self.checks), 2)       # antes da pergunta e antes de aplicar
                self.assertTrue(self.writes())
                self.assertEqual(self.shown[-1][0], 'info')
        self.assertEqual([e['status'] for e in self.panel.journal.entries()],
                         ['applied'] * len(self.panel.journal.entries()))

    def test_without_point_refuses_with_help(self):
        for tab in (8, 9):
            with self.subTest(tab=tab):
                self.restore_calls.clear()
                self.run_tab(tab)
                self.assertIn('Antes, o app cria um ponto de restauração', self.asked[-1][1])
                self.assertEqual(len(self.restore_calls), 1)
                message = cj.MSG_RESTORE_POINT_FAILED + ' ' + ou.POWER_RESTORE_POINT_HELP
                self.assertEqual(self.shown[-1][2], message)
                self.assertEqual(self.status(tab), message)
                self.assertEqual(self.writes(), [])
        self.assertFalse(self.panel.journal.entries())

    def test_point_gone_before_apply_refuses_without_help(self):
        for tab in (8, 9):
            with self.subTest(tab=tab):
                self.check_answers = [datetime.now(timezone.utc) - timedelta(minutes=9), None]
                self.run_tab(tab)
                self.assertIn('que ele mesmo criou', self.asked[-1][1])
                self.assertEqual(self.shown[-1], ('warning', ou.TWEAKS_TITLE if tab == 8
                                                  else ou.ADVANCED_TITLE, cj.MSG_REUSE_GONE))
                self.assertNotIn(ou.POWER_RESTORE_POINT_HELP, self.status(tab))
                self.assertEqual(self.restore_calls, [])
                self.assertEqual(self.writes(), [])
        self.assertFalse(self.panel.journal.entries())

    def test_read_only_button_does_not_check(self):
        self.panel.refresh_tweaks()
        self.settle()
        self.panel.refresh_advanced()
        self.settle()
        self.assertEqual(self.checks, [])

    def test_running_texts(self):
        self.assertEqual(ou.TWEAKS_RUNNING_REUSE_TEXT, 'Conferindo o ponto de restauração e aplicando '
                         'os ajustes… Isto pode demorar um pouco.')
        self.assertEqual(ou.ADVANCED_RUNNING_REUSE_TEXT, 'Conferindo o ponto de restauração e aplicando '
                         'o ajuste… Isto pode demorar um pouco.')


if __name__ == '__main__':
    unittest.main()
