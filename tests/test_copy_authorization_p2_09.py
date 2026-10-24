"""P2-09 slice 3a: the person's authorization for the protected copy.

Only fake disk inventories and synthetic files inside TemporaryDirectory.
No real disk, command, PowerShell, WMI or registry is used.
"""
import ast
import copy
import hashlib
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_disks_p2_09 import CountingCollector, fake_inventory  # noqa: E402

import backup_core  # noqa: E402
import copy_authorization as ca  # noqa: E402
import multi_source_executor as executor  # noqa: E402
from multi_source_plan import prepare_multi_source_preview  # noqa: E402
from multi_source_targets import preview_multi_source_targets  # noqa: E402
from transfer_engine import choose_strategy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOCK = 'copy' + '_authorized'
FORBIDDEN_POSITIVE = ('liberado', 'pode copiar', 'Discos separados')


def sample_preview(**changes):
    """A synthetic preview in the executor's shape (no disk involved)."""
    preview = {
        'schema': executor.PREVIEW_SCHEMA,
        'sources': ['/falso/origem_A', '/falso/origem_B'],
        'destinations': [
            {'number': 1, 'path': '/falso/destino_T', 'volume': 'T:',
             'free_bytes': 100, 'resume': False},
            {'number': 2, 'path': '/falso/destino_U', 'volume': 'U:',
             'free_bytes': 200, 'resume': False},
        ],
        'files_per_copy': 2,
        'bytes_per_copy': 1000,
        'copies': 2,
        'bytes_total': 2000,
        'physical_check': {'veredito': 'independentes',
                           'texto': 'Discos separados: texto qualquer.'},
    }
    preview.update(changes)
    return preview


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class AuthorizeTests(unittest.TestCase):
    def assertRefused(self, auth):
        self.assertIs(auth[LOCK], False)
        self.assertIsNone(auth['token'])
        self.assertEqual(set(auth), {LOCK, 'fingerprint', 'token', 'emitida_em',
                                     'motivo'})
        self.assertIsInstance(auth['motivo'], str)
        for word in FORBIDDEN_POSITIVE:
            self.assertNotIn(word, auth['motivo'])
        self.assertNotIn('/', auth['motivo'])
        self.assertNotIn('\\', auth['motivo'])
        self.assertNotIn('falso', auth['motivo'])

    def test_schema_name_matches_the_executor(self):
        self.assertEqual(ca.PREVIEW_SCHEMA, executor.PREVIEW_SCHEMA)
        self.assertEqual(ca.PREVIEW_SCHEMA, 'pcro-multi-source-executor-preview-v1')

    def test_true_only_when_everything_is_valid(self):
        auth = ca.authorize_copy(sample_preview(), user_confirmed=True,
                                 clock=FakeClock())
        self.assertIs(auth[LOCK], True)
        self.assertEqual(auth['fingerprint'], ca.preview_fingerprint(sample_preview()))
        self.assertIsInstance(auth['token'], str)
        self.assertGreaterEqual(len(auth['token']), 32)
        self.assertEqual(auth['emitida_em'], 1000.0)
        self.assertIsNone(auth['motivo'])

    def test_confirmation_must_be_exactly_true(self):
        for value in (1, 'sim', None, False, 'True', [True], 1.0):
            with self.subTest(value=value):
                self.assertRefused(ca.authorize_copy(
                    sample_preview(), user_confirmed=value, clock=FakeClock()))

    def test_verdict_schema_and_copies(self):
        cases = {
            'duvida': sample_preview(physical_check={'veredito': 'duvida', 'texto': ''}),
            'mesmo_disco': sample_preview(
                physical_check={'veredito': 'mesmo_disco', 'texto': ''}),
            'schema': sample_preview(schema='pcro-outro-schema-v1'),
            'zero': sample_preview(copies=0, destinations=[]),
            'bool': sample_preview(copies=True),
            'mismatch': sample_preview(copies=3),
        }
        for label, preview in cases.items():
            with self.subTest(label):
                self.assertRefused(ca.authorize_copy(
                    preview, user_confirmed=True, clock=FakeClock()))

    def test_malformed_preview_is_false_without_exception(self):
        no_check = sample_preview()
        del no_check['physical_check']
        no_resume = sample_preview()
        del no_resume['destinations'][0]['resume']
        cases = [None, 'texto', [], {}, no_check, no_resume,
                 sample_preview(sources='x'),
                 sample_preview(destinations='x'),
                 sample_preview(destinations=[1]),
                 sample_preview(files_per_copy='2'),
                 sample_preview(physical_check='independentes'),
                 sample_preview(physical_check={'veredito': None})]
        for preview in cases:
            with self.subTest(preview=repr(preview)[:40]):
                self.assertRefused(ca.authorize_copy(
                    preview, user_confirmed=True, clock=FakeClock()))

    def test_bad_clock_is_false_without_exception(self):
        def broken():
            raise RuntimeError('relógio quebrado')
        for clock in (broken, lambda: 'agora', lambda: None):
            with self.subTest(clock=clock):
                self.assertRefused(ca.authorize_copy(
                    sample_preview(), user_confirmed=True, clock=clock))


class FingerprintTests(unittest.TestCase):
    def test_free_bytes_and_text_are_left_out(self):
        base = ca.preview_fingerprint(sample_preview())
        other = sample_preview()
        other['destinations'][0]['free_bytes'] = 1
        other['physical_check']['texto'] = 'outro texto'
        other['bytes_total'] = 5
        self.assertEqual(ca.preview_fingerprint(other), base)
        self.assertEqual(len(base), 64)

    def test_malformed_raises_value_error(self):
        for preview in (None, {}, sample_preview(copies='2')):
            with self.subTest(preview=repr(preview)[:30]):
                with self.assertRaises(ValueError):
                    ca.preview_fingerprint(preview)


def changed_previews():
    def edit(func):
        preview = sample_preview()
        func(preview)
        return preview
    return {
        'destino': edit(lambda p: p['destinations'][0].update(path='/falso/outro')),
        'volume': edit(lambda p: p['destinations'][1].update(volume='V:')),
        'resume': edit(lambda p: p['destinations'][0].update(resume=True)),
        'bytes': edit(lambda p: p.update(bytes_per_copy=1001)),
        'arquivos': edit(lambda p: p.update(files_per_copy=3)),
        'veredito': edit(lambda p: p['physical_check'].update(veredito='duvida')),
        'origem': edit(lambda p: p['sources'].append('/falso/origem_C')),
        'schema': edit(lambda p: p.update(schema='pcro-outro')),
        'copias': edit(lambda p: p.update(copies=1, destinations=p['destinations'][:1])),
    }


class ConsumeTests(unittest.TestCase):
    def auth(self, clock=None):
        return ca.authorize_copy(sample_preview(), user_confirmed=True,
                                 clock=clock or FakeClock())

    def test_same_preview_is_accepted_once(self):
        clock = FakeClock()
        auth = self.auth(clock)
        self.assertIs(ca.consume_authorization(auth, sample_preview(), clock=clock), True)
        # Same token a second time.
        self.assertIs(ca.consume_authorization(auth, sample_preview(), clock=clock), False)
        self.assertIs(ca.consume_authorization(copy.deepcopy(auth), sample_preview(),
                                               clock=clock), False)

    def test_changed_preview_is_refused(self):
        for label, preview in changed_previews().items():
            with self.subTest(label):
                clock = FakeClock()
                self.assertIs(ca.consume_authorization(
                    self.auth(clock), preview, clock=clock), False)

    def test_only_free_bytes_changed_is_accepted(self):
        clock = FakeClock()
        preview = sample_preview()
        preview['destinations'][0]['free_bytes'] = 7
        preview['destinations'][1]['free_bytes'] = 0
        self.assertIs(ca.consume_authorization(self.auth(clock), preview, clock=clock),
                      True)

    def test_expires_after_five_minutes(self):
        clock = FakeClock()
        auth = self.auth(clock)
        clock.now += 5 * 60 + 1
        self.assertIs(ca.consume_authorization(auth, sample_preview(), clock=clock), False)
        # Exactly 5 minutes is still valid.
        clock = FakeClock()
        auth = self.auth(clock)
        clock.now += 5 * 60
        self.assertIs(ca.consume_authorization(auth, sample_preview(), clock=clock), True)
        # A clock going backwards is refused.
        clock = FakeClock()
        auth = self.auth(clock)
        clock.now -= 1
        self.assertIs(ca.consume_authorization(auth, sample_preview(), clock=clock), False)

    def test_forged_or_refused_authorizations_are_refused(self):
        clock = FakeClock()
        good = self.auth(clock)
        forged = [
            None, {}, 'sim', {LOCK: True},
            dict(good, **{LOCK: 1}),
            dict(good, token='0' * 64),
            dict(good, fingerprint='0' * 64),
            dict(good, emitida_em=good['emitida_em'] + 1000),
            ca.authorize_copy(sample_preview(), user_confirmed=False, clock=clock),
        ]
        for auth in forged:
            with self.subTest(auth=repr(auth)[:40]):
                self.assertIs(ca.consume_authorization(
                    auth, sample_preview(), clock=clock), False)

    def test_any_refusal_uses_the_registered_token_up(self):
        clock = FakeClock()
        for label, change in (('trava 1', lambda a: dict(a, **{LOCK: 1})),
                              ('fingerprint', lambda a: dict(a, fingerprint='0')),
                              ('hora', lambda a: dict(a, emitida_em=1.0))):
            with self.subTest(label):
                auth = self.auth(clock)
                self.assertIs(ca.consume_authorization(
                    change(auth), sample_preview(), clock=clock), False)
                self.assertNotIn(auth['token'], ca._ISSUED)
                self.assertIs(ca.consume_authorization(
                    auth, sample_preview(), clock=clock), False)
        auth = self.auth(clock)
        self.assertIs(ca.consume_authorization(
            auth, changed_previews()['destino'], clock=clock), False)
        self.assertNotIn(auth['token'], ca._ISSUED)

    def test_malformed_current_preview_is_false_without_exception(self):
        for preview in (None, {}, 'x', sample_preview(copies='2')):
            with self.subTest(preview=repr(preview)[:30]):
                clock = FakeClock()
                self.assertIs(ca.consume_authorization(
                    self.auth(clock), preview, clock=clock), False)

    def test_old_tokens_are_dropped_when_a_new_one_is_issued(self):
        old = self.auth(FakeClock(0.0))
        recent = self.auth(FakeClock(100.0))
        self.assertIn(old['token'], ca._ISSUED)
        newest = self.auth(FakeClock(5 * 60 + 1.0))
        self.assertNotIn(old['token'], ca._ISSUED)
        self.assertIn(recent['token'], ca._ISSUED)
        self.assertIn(newest['token'], ca._ISSUED)
        clock = FakeClock(5 * 60 + 1.0)
        self.assertIs(ca.consume_authorization(old, sample_preview(), clock=clock),
                      False)
        self.assertIs(ca.consume_authorization(recent, sample_preview(), clock=clock),
                      True)

    def test_discard_uses_up_the_token(self):
        clock = FakeClock()
        auth = self.auth(clock)
        ca.discard_authorization(auth)
        self.assertNotIn(auth['token'], ca._ISSUED)
        self.assertIs(ca.consume_authorization(auth, sample_preview(), clock=clock),
                      False)
        for bad in (None, {}, 'x', {'token': 1}):
            ca.discard_authorization(bad)  # never raises

    def test_clock_is_required_keyword_only(self):
        param = inspect.signature(ca.consume_authorization).parameters['clock']
        self.assertIs(param.default, inspect.Parameter.empty)
        self.assertIs(param.kind, inspect.Parameter.KEYWORD_ONLY)
        param = inspect.signature(ca.authorize_copy).parameters['user_confirmed']
        self.assertIs(param.default, inspect.Parameter.empty)
        self.assertIs(param.kind, inspect.Parameter.KEYWORD_ONLY)


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-autorizacao-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.sandbox = self.root / 'sandbox'
        self.folders = {}
        self.sandbox.mkdir()
        for name in ('source_A', 'source_B', 'target_T', 'target_U'):
            folder = self.sandbox / name
            folder.mkdir()
            self.folders[name] = folder
        self.first = self.folders['source_A'] / 'documento.txt'
        self.second = self.folders['source_B'] / 'jogo.sav'
        self.first.write_bytes(b'doc' * 100)
        self.second.write_bytes(b'save' * 100)
        self.plan = prepare_multi_source_preview(
            [str(self.first), str(self.second)],
            [str(self.folders['source_A']), str(self.folders['source_B'])])
        self.state = self.source_state()
        for target, value in (
                ('choose_strategy',
                 lambda src, dst, inventory=None: choose_strategy(src, dst, inventory={})),
                ('free_space', lambda folder: 100 * 1024 ** 3)):
            patcher = patch.object(backup_core, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def volume(self, raw):
        path = Path(raw)
        for name, drive in (('source_A', 'A:'), ('source_B', 'B:'),
                            ('target_T', 'T:'), ('target_U', 'U:')):
            folder = self.folders[name]
            if path == folder or folder in path.parents:
                return drive
        return 'S:'

    @staticmethod
    def usage(_):
        return SimpleNamespace(free=100 * 1024 ** 3)

    def preview(self, paths=None):
        paths = paths or [str(self.folders['target_T']), str(self.folders['target_U'])]
        return preview_multi_source_targets(
            self.plan, paths, usage=self.usage, volume_lookup=self.volume)

    def kwargs(self, collector=None):
        return dict(test_root=str(self.sandbox), volume_lookup=self.volume,
                    usage=self.usage, disk_collector=collector or CountingCollector())

    def source_state(self):
        return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in (self.first, self.second)}

    def tree(self, name):
        return sorted(p.name for p in self.folders[name].rglob('*'))

    def _autorizar(self, preview, collector=None):
        info = executor.preview_execution(self.plan, preview, **self.kwargs(collector))
        return ca.authorize_copy(info, user_confirmed=True)

    def assertRefusedNothingWritten(self, authorization, preview=None):
        with patch.object(backup_core, 'copy_backup',
                          side_effect=AssertionError('não podia copiar')) as copier:
            with self.assertRaises(ValueError) as caught:
                executor.run_protected_copy(
                    self.plan, preview or self.preview(), **self.kwargs(),
                    authorization=authorization)
        copier.assert_not_called()
        self.assertEqual(str(caught.exception), executor.REFUSED_CONFIRM)
        self.assertEqual(self.tree('target_T'), [])
        self.assertEqual(self.tree('target_U'), [])
        self.assertEqual(self.source_state(), self.state)

    def test_authorization_is_required_keyword_only(self):
        param = inspect.signature(executor.run_protected_copy).parameters['authorization']
        self.assertIs(param.default, inspect.Parameter.empty)
        self.assertIs(param.kind, inspect.Parameter.KEYWORD_ONLY)
        with self.assertRaises(TypeError):
            executor.run_protected_copy(self.plan, self.preview(), **self.kwargs())
        self.assertEqual(self.tree('target_T'), [])

    def test_refused_message_text(self):
        self.assertEqual(
            executor.REFUSED_CONFIRM,
            'Cópia recusada: falta a sua confirmação para esta prévia, ou ela '
            'mudou ou expirou. Faça a prévia e confirme de novo. Nada foi gravado.')

    def test_bad_authorizations_refuse_before_first_byte(self):
        not_confirmed = ca.authorize_copy(
            executor.preview_execution(self.plan, self.preview(), **self.kwargs()),
            user_confirmed='sim')
        cases = {
            'nenhuma': None,
            'vazia': {},
            'forjada': {LOCK: True, 'token': 'x', 'fingerprint': 'y', 'emitida_em': 0},
            'nao confirmada': not_confirmed,
        }
        for label, authorization in cases.items():
            with self.subTest(label):
                self.assertRefusedNothingWritten(authorization)

    def test_authorization_for_other_preview_is_refused(self):
        only_t = self.preview([str(self.folders['target_T'])])
        self.assertRefusedNothingWritten(self._autorizar(only_t))

    def test_authorization_made_with_doubtful_disks_is_refused(self):
        auth = self._autorizar(self.preview(), CountingCollector(None))
        self.assertIs(auth[LOCK], False)
        self.assertRefusedNothingWritten(auth)

    def test_expired_authorization_is_refused(self):
        clock = FakeClock(0.0)
        info = executor.preview_execution(self.plan, self.preview(), **self.kwargs())
        auth = ca.authorize_copy(info, user_confirmed=True, clock=clock)
        with patch.object(executor.time, 'monotonic', lambda: 5 * 60 + 1.0):
            self.assertRefusedNothingWritten(auth)

    def test_good_authorization_copies_and_is_used_once(self):
        auth = self._autorizar(self.preview())
        self.assertIs(auth[LOCK], True)
        result = executor.run_protected_copy(
            self.plan, self.preview(), **self.kwargs(), authorization=auth)
        self.assertEqual(result['status'], 'verificado')
        self.assertEqual(result['copies_verified'], 2)
        self.assertNotIn(LOCK, result)
        self.assertEqual(self.source_state(), self.state)
        # The same authorization cannot start a second copy.
        before_t, before_u = self.tree('target_T'), self.tree('target_U')
        with self.assertRaises(ValueError) as caught:
            executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs(), authorization=auth)
        self.assertEqual(str(caught.exception), executor.REFUSED_CONFIRM)
        self.assertEqual((self.tree('target_T'), self.tree('target_U')),
                         (before_t, before_u))

    def test_disk_refusal_still_comes_first(self):
        auth = self._autorizar(self.preview())
        same = fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3})
        with self.assertRaisesRegex(ValueError, 'Cópia recusada: não deu'):
            executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs(CountingCollector(same)),
                authorization=auth)
        self.assertEqual(self.tree('target_T'), [])
        # The disk refusal used the token up: a retry needs a new confirmation.
        self.assertNotIn(auth['token'], ca._ISSUED)
        self.assertRefusedNothingWritten(auth)

    def test_earlier_refusals_also_use_the_token_up(self):
        relative = self.preview()
        relative['destinations'][0]['path'] = 'target_T'
        cases = {
            'area de teste': dict(test_root=None),
            'destino relativo': dict(preview=relative),
            'coletor com erro': dict(collector=CountingCollector(error=OSError('x'))),
        }
        for label, case in cases.items():
            with self.subTest(label):
                auth = self._autorizar(self.preview())
                values = self.kwargs(case.get('collector'))
                if 'test_root' in case:
                    values['test_root'] = case['test_root']
                with self.assertRaises(ValueError) as caught:
                    executor.run_protected_copy(
                        self.plan, case.get('preview') or self.preview(), **values,
                        authorization=auth)
                self.assertNotEqual(str(caught.exception), executor.REFUSED_CONFIRM)
                self.assertNotIn(auth['token'], ca._ISSUED)
                self.assertRefusedNothingWritten(auth)

    def test_not_authorized_text_says_what_to_do(self):
        self.assertTrue(ca.NOT_AUTHORIZED.endswith(
            'Faça a prévia e confirme de novo.'))

    def test_negative_texts_never_sound_positive(self):
        texts = [executor.REFUSED_CONFIRM, ca.NOT_AUTHORIZED,
                 ca.authorize_copy(None, user_confirmed=True)['motivo']]
        for text in texts:
            for word in FORBIDDEN_POSITIVE:
                self.assertNotIn(word, text)
            self.assertNotIn(str(self.root), text)


class CodeShapeTests(unittest.TestCase):
    def setUp(self):
        self.code = (ROOT / 'copy_authorization.py').read_text(encoding='utf-8')

    def test_module_never_touches_other_locks_commands_or_deletes(self):
        for word in ('deletions_authorized', 'ready_for_format',
                     'installation_authorized', 'subprocess', 'diagnostics',
                     'unlink', 'rmtree', 'remove(', 'rmdir', 'os.replace',
                     'rename', 'tkinter', 'open(', 'Path('):
            with self.subTest(word=word):
                self.assertNotIn(word, self.code)

    def test_lock_true_only_from_one_expression(self):
        tree = ast.parse(self.code)
        # The lock key only ever holds the literal False or that one name.
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == LOCK:
                        ok = ((isinstance(value, ast.Constant) and value.value is False)
                              or (isinstance(value, ast.Name) and value.id == LOCK))
                        self.assertTrue(ok, ast.unparse(value))
        assigned = [node for node in ast.walk(tree)
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == LOCK
                            for t in node.targets)]
        self.assertEqual(len(assigned), 1)
        self.assertIsInstance(assigned[0].value, ast.BoolOp)
        self.assertIn('user_confirmed is True', ast.unparse(assigned[0].value))
        self.assertIn("veredito == 'independentes'", ast.unparse(assigned[0].value))

    def test_app_and_screens_do_not_import_module_or_executor(self):
        files = [ROOT / 'app.py', *sorted(ROOT.glob('*_ui.py'))]
        self.assertGreater(len(files), 1)
        for path in files:
            text = path.read_text(encoding='utf-8')
            with self.subTest(file=path.name):
                self.assertNotIn('copy_authorization', text)
                self.assertNotIn('multi_source_executor', text)


if __name__ == '__main__':
    unittest.main()
