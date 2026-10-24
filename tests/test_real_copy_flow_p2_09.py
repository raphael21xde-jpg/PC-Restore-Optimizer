"""P2-09 slice 3b-1: real mode of the executor and the screen controller.

Only fake disk inventories and synthetic files inside TemporaryDirectory.
No real disk, command, PowerShell, WMI or registry is used, and no tkinter.
The "real mode" happy path swaps ``validate_target`` for a wrapper that
calls the original with ``test_root=<temp>``; without it the real mode
refuses (C: or a system that is not Windows).
"""
import ast
import contextlib
import dataclasses
import hashlib
import inspect
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_disks_p2_09 import (FAKE_MODEL, FAKE_SERIAL, CountingCollector,  # noqa: E402
                              fake_inventory)

import backup_core  # noqa: E402
import copy_authorization as ca  # noqa: E402
import multi_source_executor as executor  # noqa: E402
import real_copy_flow as rcf  # noqa: E402
import selective_recovery  # noqa: E402
from multi_source_plan import prepare_multi_source_preview  # noqa: E402
from multi_source_targets import preview_multi_source_targets  # noqa: E402
from transfer_engine import choose_strategy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOCK = 'copy' + '_authorized'
FORBIDDEN_POSITIVE = ('liberado', 'pode copiar', 'Discos separados')
ORIGINAL_VALIDATE = executor.validate_target


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-real-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.folders = {}
        for name in ('source_A', 'source_B', 'target_T', 'target_U'):
            folder = self.root / name
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

    # -- helpers ---------------------------------------------------------
    def temp_target(self):
        """Patch letting validate_target accept the temp folder (tests only)."""
        root = str(self.root)

        def wrapper(destination, **kwargs):
            kwargs['test_root'] = root
            return ORIGINAL_VALIDATE(destination, **kwargs)

        return patch.object(executor, 'validate_target', wrapper)

    def allow_temp_target(self):
        patcher = self.temp_target()
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
        return dict(volume_lookup=self.volume, usage=self.usage,
                    disk_collector=collector or CountingCollector())

    def source_state(self):
        return {p.name: (sha(p), p.stat().st_mtime_ns)
                for p in (self.first, self.second)}

    def tree(self, name):
        return sorted(p.name for p in self.folders[name].rglob('*'))

    def assertNothingWritten(self):
        self.assertEqual(self.tree('target_T'), [])
        self.assertEqual(self.tree('target_U'), [])
        self.assertEqual(self.source_state(), self.state)

    def assertClean(self, text):
        self.assertIsInstance(text, str)
        for bad in (str(self.root), self.root.name, 'source_A', 'target_T',
                    FAKE_SERIAL, FAKE_MODEL, 'Ficticio'):
            self.assertNotIn(bad, text)

    def flow(self, collector=None, preview=None, plan=None):
        return rcf.RealCopyFlow(plan or self.plan, preview or self.preview(),
                                **self.kwargs(collector))


class RealExecutorTests(Base):
    def authorize(self, preview=None, collector=None):
        with self.temp_target():
            info = executor.preview_real_execution(
                self.plan, preview or self.preview(), **self.kwargs(collector))
        auth = ca.authorize_copy(info, user_confirmed=True)
        self.assertIs(auth[LOCK], True)
        return auth

    def assertRefused(self, auth, *, preview=None, plan=None, collector=None,
                      pattern=None, wrap=True, resume=None, error=ValueError):
        context = self.temp_target() if wrap else patch.object(
            executor, 'validate_target', ORIGINAL_VALIDATE)
        before = self.whole_tree()
        with context, self.assertRaises(error) as caught:
            executor.run_real_copy(
                plan or self.plan, preview or self.preview(),
                **self.kwargs(collector), authorization=auth,
                resume_manifests=resume)
        if pattern is not None:
            self.assertRegex(str(caught.exception), pattern)
        self.assertEqual(self.whole_tree(), before)
        self.assertEqual(self.source_state(), self.state)
        self.assertNotIn(auth['token'], ca._ISSUED)
        return str(caught.exception)

    def whole_tree(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))

    def make_link(self, target, name):
        link = self.root / name
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'links não disponíveis: {type(error).__name__}')
        return link

    def test_malformed_call_does_not_use_the_token_up(self):
        auth = self.authorize()
        values = self.kwargs()
        with self.temp_target():
            with self.assertRaises(TypeError):
                executor.run_real_copy(self.plan, self.preview(), **values)
            with self.assertRaises(TypeError):
                executor.run_real_copy(
                    self.plan, self.preview(), values['volume_lookup'],
                    values['usage'], values['disk_collector'], auth)
            with self.assertRaises(TypeError):
                executor.run_real_copy(self.plan, self.preview(), **values,
                                       authorization=auth, extra=True)
            with self.assertRaises(TypeError):
                executor.run_real_copy(self.plan, self.preview(), 'a mais',
                                       **values, authorization=auth)
        self.assertNothingWritten()
        self.assertEqual(values['disk_collector'].calls, 0)
        # Python refused the call before any check ran: the token is still there.
        self.assertIn(auth['token'], ca._ISSUED)
        with self.temp_target():
            result = executor.run_real_copy(
                self.plan, self.preview(), **self.kwargs(), authorization=auth)
        self.assertEqual(result['status'], 'verificado')

    def test_missing_source_or_target_is_refused(self):
        missing = self.root / 'nao_existe'
        cases = {
            'pasta escolhida': dict(plan=dataclasses.replace(
                self.plan, selected=[*self.plan.selected, str(missing)])),
            'arquivo de origem': dict(plan=dataclasses.replace(
                self.plan, files=[dataclasses.replace(
                    self.plan.files[0], source=str(missing / 'x.txt')),
                    *self.plan.files[1:]])),
            'destino': dict(preview=self.preview()),
        }
        cases['destino']['preview']['destinations'][0]['path'] = str(missing)
        for label, case in cases.items():
            with self.subTest(label):
                auth = self.authorize()
                collector = CountingCollector()
                self.assertRefused(auth, collector=collector, error=OSError, **case)
                self.assertEqual(collector.calls, 0)
        self.assertFalse(missing.exists())

    def test_link_on_the_source_side_is_refused(self):
        link = self.make_link(self.folders['source_A'], 'atalho_A')
        through = dataclasses.replace(
            self.plan, files=[dataclasses.replace(
                self.plan.files[0], source=str(link / self.first.name)),
                *self.plan.files[1:]])
        selected = dataclasses.replace(
            self.plan, selected=[str(link), *self.plan.selected[1:]])
        for label, plan in (('arquivo', through), ('pasta escolhida', selected)):
            with self.subTest(label):
                auth = self.authorize()
                self.assertRefused(auth, plan=plan, pattern='Link/junção')

    def test_bad_resume_manifests_are_refused(self):
        target = self.folders['target_T']
        real = target / 'copia_antiga'
        real.mkdir()
        (real / 'manifest.json').write_text('{}', encoding='utf-8')
        other = self.root / 'outra' / 'copia'
        other.mkdir(parents=True)
        (other / 'manifest.json').write_text('{}', encoding='utf-8')
        link = target / 'atalho'
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            link = None
        cases = [
            ('fora do destino', str(other / 'manifest.json'), ValueError,
             'inválido para este destino'),
            ('inexistente', str(target / 'nada' / 'manifest.json'), OSError, None),
        ]
        if link is not None:
            cases.append(('com link', str(link / 'manifest.json'), ValueError,
                          'Link/junção'))
        for label, manifest, error, pattern in cases:
            with self.subTest(label):
                auth = self.authorize()
                collector = CountingCollector()
                self.assertRefused(auth, resume={str(target): manifest},
                                   collector=collector, error=error,
                                   pattern=pattern)
                self.assertEqual(collector.calls, 0)
        self.assertEqual((real / 'manifest.json').read_text(encoding='utf-8'), '{}')

    def test_source_changed_after_plan_is_refused(self):
        auth = self.authorize()
        self.second.write_bytes(b'mudou' * 100)
        self.state = self.source_state()
        collector = CountingCollector()
        self.assertRefused(auth, collector=collector, pattern='Fonte modificada')
        self.assertEqual(collector.calls, 0)
        self.assertEqual(self.tree('target_T'), [])
        self.assertEqual(self.tree('target_U'), [])

    def test_required_keyword_only_arguments(self):
        for func, names in ((executor.preview_real_execution, ('disk_collector',)),
                            (executor.run_real_copy,
                             ('disk_collector', 'authorization'))):
            params = inspect.signature(func).parameters
            self.assertNotIn('test_root', params)
            for name in names:
                with self.subTest(func=func.__name__, name=name):
                    self.assertIs(params[name].default, inspect.Parameter.empty)
                    self.assertIs(params[name].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_happy_path_copies_and_verifies(self):
        auth = self.authorize()
        self.allow_temp_target()
        result = executor.run_real_copy(
            self.plan, self.preview(), **self.kwargs(), authorization=auth)
        self.assertEqual(result['status'], 'verificado')
        self.assertEqual(result['copies_verified'], 2)
        self.assertNotIn(LOCK, result)
        self.assertNotIn(auth['token'], ca._ISSUED)
        for target in ('target_T', 'target_U'):
            copied = list(self.folders[target].rglob('documento.txt'))
            self.assertEqual(len(copied), 1)
            self.assertEqual(sha(copied[0]), sha(self.first))
        self.assertEqual(self.source_state(), self.state)

    def test_without_wrapper_real_mode_refuses_c_or_not_windows(self):
        auth = self.authorize()
        self.assertIs(executor.validate_target, ORIGINAL_VALIDATE)
        collector = CountingCollector()
        self.assertRefused(auth, collector=collector, wrap=False,
                           pattern='unidade diferente de C:')
        # Refused before the disk query: the collector was never called.
        self.assertEqual(collector.calls, 0)

    def test_drive_root_is_refused_as_target_and_source(self):
        # ``anchor`` is the root of the drive that holds the TEMP folder; the
        # test only expects the refusal, and nothing is ever written there.
        anchor = Path(self.root.anchor)
        auth = self.authorize()
        preview = self.preview()
        preview['destinations'][0]['path'] = str(anchor)
        self.assertRefused(auth, preview=preview, pattern='raiz de uma unidade')
        auth = self.authorize()
        plan = dataclasses.replace(
            self.plan, selected=[str(anchor), *self.plan.selected])
        self.assertRefused(auth, plan=plan, pattern='raiz de uma unidade')
        with self.assertRaisesRegex(ValueError, 'raiz de uma unidade'):
            executor.preview_real_execution(self.plan, preview, **self.kwargs())

    def test_link_or_junction_is_refused(self):
        link = self.make_link(self.folders['target_T'], 'atalho_T')
        auth = self.authorize()
        preview = self.preview()
        preview['destinations'][0]['path'] = str(link)
        self.assertRefused(auth, preview=preview, pattern='Link/junção')
        inner = link / 'dentro'
        auth = self.authorize()
        preview = self.preview()
        preview['destinations'][0]['path'] = str(inner)
        self.assertRefused(auth, preview=preview)
        self.assertEqual(self.tree('target_T'), [])

    def test_target_inside_source_and_source_inside_target(self):
        inside = self.folders['source_A'] / 'dentro'
        inside.mkdir()
        for folder in (inside, self.root):
            with self.subTest(folder=folder.name):
                auth = self.authorize()
                preview = self.preview()
                preview['destinations'][0]['path'] = str(folder)
                self.assertRefused(auth, preview=preview, pattern='sobrepor')
                self.assertEqual(sorted(p.name for p in inside.iterdir()), [])

    def test_same_disk_or_doubt_refuses(self):
        same = fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3})
        for label, collector in (('mesmo_disco', CountingCollector(same)),
                                 ('duvida', CountingCollector(None))):
            with self.subTest(label):
                auth = self.authorize()
                text = self.assertRefused(auth, collector=collector,
                                          pattern='Cópia recusada: não deu')
                self.assertEqual(collector.calls, 1)
                self.assertClean(text)

    def test_changed_preview_is_refused(self):
        auth = self.authorize(self.preview([str(self.folders['target_T'])]))
        self.assertEqual(self.assertRefused(auth), executor.REFUSED_CONFIRM)

    def test_expired_authorization_is_refused(self):
        with self.temp_target():
            info = executor.preview_real_execution(
                self.plan, self.preview(), **self.kwargs())
        auth = ca.authorize_copy(info, user_confirmed=True, clock=lambda: 0.0)
        # Only the executor's clock moves; time.monotonic of the process stays.
        late = SimpleNamespace(monotonic=lambda: 5 * 60 + 1.0)
        with patch.object(executor, 'time', late):
            self.assertEqual(self.assertRefused(auth), executor.REFUSED_CONFIRM)

    def test_order_paths_then_disks_then_authorization(self):
        # A bad path is refused before the disk query and before the token.
        relative = self.preview()
        relative['destinations'][0]['path'] = 'target_T'
        auth = self.authorize()
        collector = CountingCollector()
        self.assertRefused(auth, preview=relative, collector=collector)
        self.assertEqual(collector.calls, 0)
        # Without an authorization the disks are still checked first.
        collector = CountingCollector(None)
        with self.temp_target(), \
                self.assertRaisesRegex(ValueError, 'Cópia recusada: não deu'):
            executor.run_real_copy(self.plan, self.preview(),
                                   **self.kwargs(collector), authorization=None)
        self.assertNothingWritten()

    def test_test_area_functions_still_not_released(self):
        auth = self.authorize()
        with self.assertRaisesRegex(ValueError, 'ainda não liberado'):
            executor.preview_execution(self.plan, self.preview(), test_root=None,
                                       **self.kwargs())
        with self.assertRaises(ValueError) as caught:
            executor.run_protected_copy(self.plan, self.preview(), test_root=None,
                                        **self.kwargs(), authorization=auth)
        self.assertEqual(str(caught.exception), executor.NOT_RELEASED)
        self.assertNotIn(auth['token'], ca._ISSUED)
        self.assertNothingWritten()


class FlowTests(Base):
    def test_no_disk_query_without_warning_and_true(self):
        collector = CountingCollector()
        flow = self.flow(collector)
        self.assertEqual(flow.state, rcf.INICIO)
        self.assertEqual(flow.confirm_disk_check(True), rcf.INICIO)
        self.assertEqual(collector.calls, 0)
        for value in (1, 'sim', None, False, 'True', [True], 1.0):
            with self.subTest(value=value):
                self.assertEqual(flow.request_disk_check(), rcf.AVISO_CONSULTA)
                self.assertEqual(flow.message, rcf.AVISO_CONSULTA_TEXTO)
                self.assertEqual(flow.confirm_disk_check(value), rcf.INICIO)
                self.assertEqual(collector.calls, 0)
        self.assertNothingWritten()

    def test_warning_text(self):
        text = rcf.AVISO_CONSULTA_TEXTO
        self.assertIn('vou só ler a lista de discos', text)
        self.assertIn('nada é gravado, formatado nem apagado', text)

    def test_collector_is_required_keyword_only(self):
        param = inspect.signature(rcf.RealCopyFlow).parameters['disk_collector']
        self.assertIs(param.default, inspect.Parameter.empty)
        self.assertIs(param.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_run_without_confirmation_refuses(self):
        self.allow_temp_target()
        for answer in (None, False, 'sim', 1):
            with self.subTest(answer=answer):
                collector = CountingCollector()
                flow = self.flow(collector)
                flow.request_disk_check()
                self.assertEqual(flow.confirm_disk_check(True), rcf.PREVIA)
                self.assertEqual(collector.calls, 1)
                if answer is not None:
                    self.assertEqual(flow.confirm_copy(answer), rcf.PREVIA)
                with patch.object(backup_core, 'copy_backup',
                                  side_effect=AssertionError('não podia copiar')):
                    self.assertEqual(flow.run(), rcf.RECUSADO)
                self.assertEqual(flow.message, executor.REFUSED_CONFIRM)
                self.assertEqual(collector.calls, 1)
                self.assertNothingWritten()
        flow = self.flow()
        self.assertEqual(flow.run(), rcf.RECUSADO)
        self.assertEqual(flow.message, executor.REFUSED_CONFIRM)

    def test_happy_path(self):
        self.allow_temp_target()
        collector = CountingCollector()
        flow = self.flow(collector)
        flow.request_disk_check()
        self.assertEqual(flow.confirm_disk_check(True), rcf.PREVIA)
        text = flow.preview_text()
        self.assertIn('Origens: 2 pasta(s)', text)
        self.assertIn('Destino 1 (unidade T:)', text)
        self.assertIn('Destino 2 (unidade U:)', text)
        self.assertIn('Cada cópia tem 2 arquivo(s)', text)
        self.assertIn(rcf.VERDICT_TEXT['independentes'], text)
        self.assertClean(text)
        self.assertEqual(flow.confirm_copy(True), rcf.CONFIRMADO)
        token = flow._authorization['token']
        calls = []
        self.assertEqual(flow.run(progress=lambda *a: calls.append(a[0])),
                         rcf.CONCLUIDO)
        # One read for the preview, then a new one before each destination.
        self.assertEqual(collector.calls, 3)
        self.assertEqual(flow.result['status'], 'verificado')
        self.assertIn('Todas as cópias foram feitas e conferidas.', flow.report)
        self.assertClean(flow.report)
        self.assertNotIn(token, ca._ISSUED)
        self.assertTrue(set(calls) <= {1, 2})
        for target in ('target_T', 'target_U'):
            copied = list(self.folders[target].rglob('jogo.sav'))
            self.assertEqual(len(copied), 1)
            self.assertEqual(sha(copied[0]), sha(self.second))
        self.assertEqual(self.source_state(), self.state)
        # The flow cannot copy twice with the same confirmation.
        self.assertEqual(flow.run(), rcf.RECUSADO)

    def test_refusals_become_short_reasons(self):
        same = fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3})
        root_preview = self.preview()
        root_preview['destinations'][0]['path'] = self.root.anchor
        inside = self.folders['source_A'] / 'dentro'
        inside.mkdir()
        inside_preview = self.preview()
        inside_preview['destinations'][0]['path'] = str(inside)
        cases = [
            ('sem invólucro', False, {}, rcf.MSG_UNIDADE),
            ('raiz', True, dict(preview=root_preview), rcf.MSG_RAIZ),
            ('dentro da origem', True, dict(preview=inside_preview), rcf.MSG_SOBREPOR),
            ('coletor com erro', True,
             dict(collector=CountingCollector(error=OSError(str(self.root)))), None),
        ]
        for label, wrap, extra, reason in cases:
            with self.subTest(label):
                # Without the wrapper the target is treated as being on C:,
                # so the refusal does not depend on the TEMP drive letter.
                drive = (patch.object(selective_recovery, 'volume_of',
                                      return_value='C:')
                         if not wrap else contextlib.nullcontext())
                with drive, patch.object(executor, 'validate_target',
                                         self._validate(wrap)):
                    flow = self.flow(**extra)
                    flow.request_disk_check()
                    state = flow.confirm_disk_check(True)
                if reason is None:
                    # A broken collector is only a doubt: the preview opens,
                    # but the copy cannot be confirmed.
                    self.assertEqual(state, rcf.PREVIA)
                    text = flow.preview_text()
                    self.assertIn(rcf.VERDICT_DOUBT, text)
                    for word in FORBIDDEN_POSITIVE:
                        self.assertNotIn(word, text)
                    self.assertEqual(flow.confirm_copy(True), rcf.PREVIA)
                    self.assertEqual(flow.message, ca.NOT_AUTHORIZED)
                    self.assertEqual(flow.run(), rcf.RECUSADO)
                else:
                    self.assertEqual(state, rcf.RECUSADO)
                    self.assertEqual(flow.message, reason)
                self.assertClean(flow.message)
                self.assertClean(flow.preview_text())
                self.assertNothingWritten()
        # Disks on the same disk: refused at copy time, nothing written.
        self.allow_temp_target()
        flow = self.flow(CountingCollector(fake_inventory(), same))
        flow.request_disk_check()
        flow.confirm_disk_check(True)
        flow.confirm_copy(True)
        token = flow._authorization['token']
        self.assertEqual(flow.run(), rcf.RECUSADO)
        self.assertEqual(flow.message, executor.REFUSED_DISKS)
        self.assertNotIn(token, ca._ISSUED)
        self.assertNothingWritten()

    def _validate(self, wrap):
        if not wrap:
            return ORIGINAL_VALIDATE
        root = str(self.root)
        return lambda destination, **kw: ORIGINAL_VALIDATE(
            destination, **dict(kw, test_root=root))

    def confirmed_flow(self):
        self.allow_temp_target()
        flow = self.flow()
        flow.request_disk_check()
        self.assertEqual(flow.confirm_disk_check(True), rcf.PREVIA)
        self.assertEqual(flow.confirm_copy(True), rcf.CONFIRMADO)
        return flow

    def test_missing_folder_is_a_clear_reason(self):
        missing = self.root / 'nao_existe'
        preview = self.preview()
        preview['destinations'][0]['path'] = str(missing)
        with self.temp_target():
            flow = self.flow(preview=preview)
            flow.request_disk_check()
            self.assertEqual(flow.confirm_disk_check(True), rcf.RECUSADO)
        self.assertEqual(flow.message, rcf.MSG_SUMIU)
        self.assertIn('Nada foi gravado', flow.message)
        for error in (FileNotFoundError(str(missing)), NotADirectoryError(str(missing))):
            with self.subTest(error=type(error).__name__):
                flow = self.confirmed_flow()
                with patch.object(executor, 'run_real_copy', side_effect=error):
                    self.assertEqual(flow.run(), rcf.RECUSADO)
                self.assertEqual(flow.message, rcf.MSG_SUMIU)
                self.assertClean(flow.message)
        self.assertNothingWritten()

    def test_cancelled_copy_is_not_concluded(self):
        import threading
        flow = self.confirmed_flow()
        event = threading.Event()
        event.set()
        self.assertEqual(flow.run(cancelled=event), rcf.INCOMPLETO)
        self.assertEqual(flow.message, rcf.MSG_INCOMPLETO)
        self.assertEqual(flow.result['status'], 'nao_verificado')
        self.assertIn('cancelado', flow.report)
        self.assertClean(flow.report)
        self.assertNothingWritten()

    def test_partial_result_is_not_concluded(self):
        flow = self.confirmed_flow()
        partial = {'status': 'parcial', 'destinations': []}
        with patch.object(executor, 'run_real_copy', return_value=partial):
            self.assertEqual(flow.run(), rcf.INCOMPLETO)
        self.assertIs(flow.result, partial)

    def test_report_failure_after_verified_copy_keeps_the_result(self):
        flow = self.confirmed_flow()
        with patch.object(executor, 'format_report_pt',
                          side_effect=RuntimeError(str(self.root))):
            self.assertEqual(flow.run(), rcf.CONCLUIDO)
        self.assertEqual(flow.result['status'], 'verificado')
        self.assertIsNone(flow.report)
        self.assertEqual(flow.message, rcf.MSG_SEM_RELATORIO)
        self.assertClean(flow.message)

    def test_unexpected_error_is_generic(self):
        self.allow_temp_target()
        flow = self.flow()
        flow.request_disk_check()
        flow.confirm_disk_check(True)
        flow.confirm_copy(True)
        with patch.object(executor, 'run_real_copy',
                          side_effect=KeyError(str(self.root))):
            self.assertEqual(flow.run(), rcf.RECUSADO)
        self.assertEqual(flow.message, rcf.MSG_INESPERADO)
        self.assertClean(flow.message)

    def test_reset_and_cancel_use_the_authorization_up(self):
        self.allow_temp_target()
        for action in ('reset', 'cancel'):
            with self.subTest(action):
                flow = self.flow()
                flow.request_disk_check()
                flow.confirm_disk_check(True)
                flow.confirm_copy(True)
                token = flow._authorization['token']
                self.assertIn(token, ca._ISSUED)
                self.assertEqual(getattr(flow, action)(), rcf.INICIO)
                self.assertNotIn(token, ca._ISSUED)
                self.assertIsNone(flow.preview)
                self.assertEqual(flow.run(), rcf.RECUSADO)
                self.assertNothingWritten()
        self.assertEqual(flow.message, executor.REFUSED_CONFIRM)

    def test_new_confirmation_discards_the_old_token(self):
        self.allow_temp_target()
        flow = self.flow()
        flow.request_disk_check()
        flow.confirm_disk_check(True)
        flow.confirm_copy(True)
        first = flow._authorization['token']
        flow.confirm_copy(False)
        self.assertNotIn(first, ca._ISSUED)
        self.assertEqual(flow.state, rcf.PREVIA)

    def test_all_texts_are_clean_and_negative_ones_never_positive(self):
        texts = [rcf.AVISO_CONSULTA_TEXTO, rcf.CANCELADO, rcf.NAO_CONFIRMADO,
                 rcf.MSG_PREVIA, rcf.MSG_UNIDADE, rcf.MSG_SOBREPOR, rcf.MSG_LINK,
                 rcf.MSG_RAIZ, rcf.MSG_MUDOU, rcf.MSG_INESPERADO, rcf.VERDICT_DOUBT,
                 rcf.MSG_SUMIU, rcf.MSG_INCOMPLETO]
        for text in texts:
            with self.subTest(text=text[:30]):
                self.assertClean(text)
                self.assertNotIn('/', text)
                self.assertNotIn('\\', text)
                for word in FORBIDDEN_POSITIVE:
                    self.assertNotIn(word, text)

    def test_engine_messages_never_pass_through(self):
        cases = {
            f'Link/junção proibido no caminho: {self.root}': rcf.MSG_LINK,
            'Fonte modificada depois do planejamento.': rcf.MSG_MUDOU,
            f'Erro qualquer em {self.root}': rcf.MSG_PREVIA,
        }
        for message, reason in cases.items():
            self.assertEqual(rcf._reason(ValueError(message)), reason)
        self.assertEqual(rcf._reason(OSError(str(self.root))), rcf.MSG_INESPERADO)


class CodeShapeTests(unittest.TestCase):
    def setUp(self):
        self.code = (ROOT / 'real_copy_flow.py').read_text(encoding='utf-8')

    def test_no_deletes_commands_or_tk(self):
        for word in ('unlink', 'rmtree', 'remove(', 'rmdir', 'os.replace',
                     'rename', 'subprocess', 'os.system', 'tkinter',
                     'powershell', 'PowerShell', 'disk_inventory', 'open(',
                     'deletions_authorized', 'ready_for_format',
                     'installation_authorized', 'physical_independence_verified',
                     'test_root'):
            with self.subTest(word=word):
                self.assertNotIn(word, self.code)

    def test_lock_name_only_read_in_one_line(self):
        lines = [line for line in self.code.splitlines() if LOCK in line]
        self.assertEqual(len(lines), 1)
        self.assertIn(f".get('{LOCK}') is not True", lines[0])
        tree = ast.parse(self.code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    self.assertFalse(isinstance(key, ast.Constant) and key.value == LOCK)
            if isinstance(node, ast.Subscript) and not isinstance(node.ctx, ast.Load):
                self.assertNotEqual(getattr(node.slice, 'value', None), LOCK)

    def test_flow_uses_only_the_real_functions(self):
        self.assertNotIn('run_protected_copy', self.code)
        self.assertNotIn('preview_execution(', self.code.replace(
            'preview_real_execution(', ''))

    def test_app_and_screens_do_not_import_flow_or_executor(self):
        files = [ROOT / 'app.py', *sorted(ROOT.glob('*_ui.py'))]
        self.assertGreater(len(files), 1)
        for path in files:
            text = path.read_text(encoding='utf-8')
            with self.subTest(file=path.name):
                self.assertIsNone(re.search(r'\breal_copy_flow\b', text))
                self.assertNotIn('multi_source_executor', text)

    def test_executor_keeps_no_lock_writes(self):
        source = (ROOT / 'multi_source_executor.py').read_text(encoding='utf-8')
        self.assertNotIn(LOCK, source)
        self.assertEqual(source.count('physical_independence_verified'), 1)


if __name__ == '__main__':
    unittest.main()
