"""P2-09 fatia 1: protected multi-disk executor, exercised only in a sandbox.

Every test uses synthetic files inside TemporaryDirectory. No real disk,
backup or user data is touched, and the app is not wired to the executor.
"""
import hashlib
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import backup_core
import multi_source_executor as executor
from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from selective_recovery import verify_complete_manifest
from transfer_engine import choose_strategy

ROOT = Path(__file__).resolve().parents[1]


def _can_symlink():
    with tempfile.TemporaryDirectory(prefix='pcro-link-probe-') as tmp:
        try:
            os.symlink(tmp, os.path.join(tmp, 'probe'), target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


CAN_SYMLINK = _can_symlink()


class ProtectedExecutorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-executor-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.sandbox = self.root / 'sandbox'
        self.outside = self.root / 'outside'
        self.source_a = self.sandbox / 'source_A'
        self.source_b = self.sandbox / 'source_B'
        self.target_t = self.sandbox / 'target_T'
        self.target_u = self.sandbox / 'target_U'
        for folder in (self.sandbox, self.outside, self.source_a, self.source_b,
                       self.target_t, self.target_u):
            folder.mkdir()
        self.first = self.source_a / 'documento.txt'
        self.second = self.source_b / 'progresso.sav'
        self.first.write_bytes(b'important-document' * 50)
        self.second.write_bytes(b'important-game-save' * 50)
        self.plan = prepare_multi_source_preview(
            [str(self.first), str(self.second)],
            [str(self.source_a), str(self.source_b)])
        self.snapshot = self.source_state()
        # Keep hardware probes and the real free-space reading out of tests.
        for target, value in (
                ('choose_strategy',
                 lambda src, dst, inventory=None: choose_strategy(src, dst, inventory={})),
                ('free_space', lambda folder: 100 * 1024 ** 3)):
            patcher = patch.object(backup_core, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    # --- helpers -------------------------------------------------------
    def volume(self, raw):
        path = Path(raw)
        for folder, drive in ((self.source_a, 'A:'), (self.source_b, 'B:'),
                              (self.target_t, 'T:'), (self.target_u, 'U:'),
                              (self.outside, 'X:')):
            if path == folder or folder in path.parents:
                return drive
        return 'S:'

    @staticmethod
    def usage(_):
        return SimpleNamespace(free=100 * 1024 ** 3)

    def preview(self, paths=None):
        return preview_multi_source_targets(
            self.plan, paths or [str(self.target_t), str(self.target_u)],
            usage=self.usage, volume_lookup=self.volume)

    def kwargs(self, **extra):
        values = dict(test_root=str(self.sandbox), volume_lookup=self.volume,
                      usage=self.usage)
        values.update(extra)
        return values

    def source_state(self):
        return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(),
                         p.stat().st_size, p.stat().st_mtime_ns)
                for p in (self.first, self.second)}

    def tree(self, folder):
        return sorted(str(p.relative_to(folder)) for p in Path(folder).rglob('*'))

    def assert_targets_empty(self):
        self.assertEqual(self.tree(self.target_t), [])
        self.assertEqual(self.tree(self.target_u), [])

    def interrupted_first_destination(self):
        """Interrupt the copy into the first destination on its second file."""
        original = backup_core.copy_backup
        writes = [0]

        def hook(stage):
            if stage == 'backup_after_write':
                writes[0] += 1
                if writes[0] == 2:
                    raise InterruptedError('synthetic interruption')

        def copy_with_fault(*args, **kwargs):
            kwargs['test_fault_hook'] = hook
            return original(*args, **kwargs)

        with patch.object(backup_core, 'copy_backup', copy_with_fault):
            result = executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs())
        self.assertEqual(result['status'], 'nao_verificado')
        first = result['destinations'][0]
        self.assertEqual(first['status'], 'interrompido')
        return result, Path(first['manifest'])

    # --- 1 ---------------------------------------------------------------
    def test_01_without_test_root_refuses_and_writes_nothing(self):
        preview = self.preview()
        for call in (executor.preview_execution, executor.run_protected_copy):
            with self.subTest(call=call.__name__):
                with self.assertRaisesRegex(ValueError, 'Executor ainda não liberado'):
                    call(self.plan, preview, **self.kwargs(test_root=None))
        self.assert_targets_empty()
        self.assertEqual(self.source_state(), self.snapshot)

    # --- 2 ---------------------------------------------------------------
    def test_02_paths_outside_test_root_refused_before_writing(self):
        preview = self.preview([str(self.target_t), str(self.outside)])
        with self.assertRaisesRegex(ValueError, 'fora da área de teste'):
            executor.run_protected_copy(self.plan, preview, **self.kwargs())
        self.assert_targets_empty()
        self.assertEqual(self.tree(self.outside), [])
        # Sources outside the sandbox are refused as well.
        inner = self.sandbox / 'only-targets'
        inner.mkdir()
        (inner / 'T').mkdir()
        with self.assertRaisesRegex(ValueError, 'fora da área de teste'):
            executor.preview_execution(
                self.plan, self.preview(), **self.kwargs(test_root=str(inner)))
        # A relative destination is refused.
        bad = self.preview()
        bad['destinations'][0]['path'] = 'target_T'
        with self.assertRaisesRegex(ValueError, 'absoluto'):
            executor.preview_execution(self.plan, bad, **self.kwargs())
        self.assert_targets_empty()

    # --- 3 ---------------------------------------------------------------
    def test_03_destination_inside_source_and_source_inside_destination(self):
        nested = self.source_a / 'backup-aqui'
        nested.mkdir()
        lookup = lambda raw: 'N:' if Path(raw) == nested else self.volume(raw)
        inside_source = preview_multi_source_targets(
            self.plan, [str(nested)], usage=self.usage, volume_lookup=lookup)
        with self.assertRaisesRegex(ValueError, 'sobrep'):
            executor.run_protected_copy(
                self.plan, inside_source, **self.kwargs(volume_lookup=lookup))
        self.assertEqual(self.tree(nested), [])
        # Destination that contains the sources (the sandbox root itself
        # is refused, so use a parent folder inside the sandbox).
        holder = self.sandbox / 'holder'
        holder.mkdir()
        src = holder / 'origem'
        src.mkdir()
        inner_file = src / 'x.txt'
        inner_file.write_bytes(b'inside-holder')
        plan = prepare_multi_source_preview([str(inner_file)], [str(src)])
        lookup2 = lambda raw: ('O:' if Path(raw) == inner_file or src in Path(raw).parents
                               else 'H:' if Path(raw) == holder else self.volume(raw))
        # The target preview itself refuses this case, so forge the row to
        # prove the executor checks it on its own.
        contains = preview_multi_source_targets(
            plan, [str(self.target_t)], usage=self.usage, volume_lookup=lookup2)
        contains['destinations'][0].update(path=str(holder), volume='H:')
        with self.assertRaisesRegex(ValueError, 'sobrep'):
            executor.run_protected_copy(
                plan, contains, **self.kwargs(volume_lookup=lookup2))
        self.assertEqual(sorted(p.name for p in holder.iterdir()), ['origem'])
        self.assert_targets_empty()

    # --- 4 ---------------------------------------------------------------
    @unittest.skipUnless(CAN_SYMLINK, 'este sistema não cria links simbólicos')
    def test_04_link_in_ancestor_source_or_destination_refused(self):
        preview = self.preview()
        # Destination reached through a link.
        real = self.sandbox / 'real_target'
        real.mkdir()
        link = self.sandbox / 'link_target'
        os.symlink(real, link, target_is_directory=True)
        linked = self.preview()
        linked['destinations'][1]['path'] = str(link)
        with self.assertRaisesRegex(ValueError, '[Ll]ink'):
            executor.run_protected_copy(self.plan, linked, **self.kwargs())
        self.assertEqual(self.tree(real), [])
        # test_root reached through a link in an ancestor.
        alias = self.root / 'alias'
        os.symlink(self.sandbox, alias, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '[Ll]ink'):
            executor.run_protected_copy(
                self.plan, preview, **self.kwargs(test_root=str(alias)))
        # Source folder swapped for a link after the plan was made.
        moved = self.sandbox / 'source_B_real'
        self.source_b.rename(moved)
        os.symlink(moved, self.source_b, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '[Ll]ink'):
            executor.run_protected_copy(self.plan, preview, **self.kwargs())
        self.assert_targets_empty()

    # --- 5 ---------------------------------------------------------------
    def test_05_preview_creates_nothing(self):
        before = self.tree(self.root)
        info = executor.preview_execution(self.plan, self.preview(), **self.kwargs())
        self.assertEqual(self.tree(self.root), before)
        self.assertEqual(info['files_per_copy'], 2)
        self.assertEqual(info['bytes_per_copy'], self.plan.total)
        self.assertEqual(info['copies'], 2)
        self.assertEqual(info['bytes_total'], 2 * self.plan.total)
        self.assertEqual(len(info['destinations']), 2)
        self.assertEqual(len(info['sources']), 2)

    # --- 6 ---------------------------------------------------------------
    def test_06_two_destinations_two_manifests_hashes_match(self):
        result = executor.run_protected_copy(self.plan, self.preview(), **self.kwargs())
        self.assertEqual(result['status'], 'verificado')
        self.assertEqual(result['copies_verified'], 2)
        manifests = [Path(row['manifest']) for row in result['destinations']]
        self.assertEqual(len(set(manifests)), 2)
        self.assertEqual(manifests[0].parent.parent, self.target_t)
        self.assertEqual(manifests[1].parent.parent, self.target_u)
        expected = {hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (self.first, self.second)}
        for row, manifest in zip(result['destinations'], manifests):
            self.assertEqual(row['status'], 'verificado')
            self.assertEqual(row['files_verified'], 2)
            doc = json.loads(manifest.read_text(encoding='utf-8'))
            self.assertEqual({item['sha256'] for item in doc['files']}, expected)
            copied = {hashlib.sha256((manifest.parent / item['relative']).read_bytes()).hexdigest()
                      for item in doc['files']}
            self.assertEqual(copied, expected)

    # --- 7 ---------------------------------------------------------------
    def test_07_sources_untouched(self):
        executor.run_protected_copy(self.plan, self.preview(), **self.kwargs())
        self.assertEqual(self.source_state(), self.snapshot)
        self.assertEqual(sorted(p.name for p in self.source_a.iterdir()), ['documento.txt'])
        self.assertEqual(sorted(p.name for p in self.source_b.iterdir()), ['progresso.sav'])

    # --- 8 ---------------------------------------------------------------
    def test_08_cancel_before_second_destination_is_partial(self):
        cancelled = threading.Event()
        original = executor.verify_complete_manifest

        def verify_then_cancel(*args, **kwargs):
            outcome = original(*args, **kwargs)
            cancelled.set()  # the user presses cancel after the first copy
            return outcome

        with patch.object(executor, 'verify_complete_manifest', verify_then_cancel):
            result = executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs(cancelled=cancelled))
        self.assertEqual(result['status'], 'parcial')
        self.assertIn('cancel', result['reason'].lower())
        self.assertEqual(result['copies_verified'], 1)
        self.assertEqual([row['status'] for row in result['destinations']],
                         ['verificado', 'cancelado'])
        self.assertEqual(self.tree(self.target_u), [])
        # Cancelled before anything: nothing is written at all.
        cancelled_early = threading.Event()
        cancelled_early.set()
        other = executor.run_protected_copy(
            self.plan, self.preview(), **self.kwargs(cancelled=cancelled_early))
        self.assertEqual(other['status'], 'nao_verificado')
        self.assertEqual(self.tree(self.target_u), [])

    # --- 9 ---------------------------------------------------------------
    def test_09_resume_after_interruption_then_source_change_refused(self):
        _, manifest = self.interrupted_first_destination()
        self.assertEqual(self.tree(self.target_u), [])
        result = executor.run_protected_copy(
            self.plan, self.preview(),
            **self.kwargs(resume_manifests={str(self.target_t): str(manifest)}))
        self.assertEqual(result['status'], 'verificado')
        self.assertEqual(Path(result['destinations'][0]['manifest']), manifest)
        self.assertEqual(verify_complete_manifest(manifest)['files_verified'], 2)
        self.assertEqual(self.source_state(), self.snapshot)

    def test_09b_resume_refused_when_source_changed(self):
        _, manifest = self.interrupted_first_destination()
        saved = manifest.read_bytes()
        self.second.write_bytes(b'changed-after-interruption')
        with self.assertRaisesRegex(ValueError, 'modificada'):
            executor.run_protected_copy(
                self.plan, self.preview(),
                **self.kwargs(resume_manifests={str(self.target_t): str(manifest)}))
        self.assertEqual(manifest.read_bytes(), saved)
        self.assertEqual(self.tree(self.target_u), [])
        # A manifest for an unknown destination is refused too.
        with self.assertRaisesRegex(ValueError, 'retomada'):
            executor.preview_execution(
                self.plan, self.preview(),
                **self.kwargs(resume_manifests={str(self.outside): str(manifest)}))

    # --- 10 --------------------------------------------------------------
    def test_10_corrupted_destination_file_is_not_verified(self):
        original = backup_core.copy_backup

        def copy_then_corrupt(*args, **kwargs):
            folder, manifest = original(*args, **kwargs)
            first = manifest['files'][0]
            target = Path(folder) / first['relative']
            target.write_bytes(b'X' * target.stat().st_size)
            return folder, manifest

        with patch.object(backup_core, 'copy_backup', copy_then_corrupt):
            result = executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs())
        self.assertEqual(result['status'], 'nao_verificado')
        self.assertEqual(result['destinations'][0]['status'], 'nao_verificado')
        self.assertEqual(result['destinations'][1]['status'], 'nao_iniciado')
        self.assertEqual(self.tree(self.target_u), [])
        self.assertIn('não verificado', executor.format_report_pt(result))
        self.assertEqual(self.source_state(), self.snapshot)

    # --- 11 --------------------------------------------------------------
    def test_11_report_is_portuguese_without_temporary_paths(self):
        result = executor.run_protected_copy(self.plan, self.preview(), **self.kwargs())
        text = executor.format_report_pt(result)
        self.assertIn('nenhum arquivo da origem foi gravado ou apagado', text)
        self.assertIn('Destino 1', text)
        self.assertIn('verificad', text)
        for secret in (str(self.root), self.root.name, tempfile.gettempdir(),
                       'pcro-executor-', 'target_T', 'source_A'):
            self.assertNotIn(secret, text)
        self.assertIsNone(re.search(r'[A-Za-z]:\\|/tmp|/home|Users', text))

    # --- 12 --------------------------------------------------------------
    def test_12_result_keys_are_exactly_the_expected_set(self):
        result = executor.run_protected_copy(self.plan, self.preview(), **self.kwargs())
        self.assertEqual(set(result), {
            'schema', 'status', 'reason', 'copies_requested', 'copies_verified',
            'files_per_copy', 'bytes_per_copy', 'destinations'})
        for row in result['destinations']:
            self.assertEqual(set(row), {
                'number', 'path', 'volume', 'status', 'manifest',
                'files_verified', 'bytes_verified', 'problem'})

    # --- FIX-P2-09-01: review notes of PR #85 ----------------------------
    def assert_cancelled_during_check(self, result):
        first, second = result['destinations']
        self.assertEqual(first['status'], 'cancelado')
        self.assertIsNotNone(first['manifest'])
        self.assertIn('conferência cancelada', first['problem'])
        self.assertIn('conferida de novo', first['problem'])
        self.assertNotIn('retomada', first['problem'])
        self.assertEqual(result['reason'], first['problem'])
        self.assertEqual(result['copies_verified'], 0)
        self.assertEqual(result['status'], 'nao_verificado')
        self.assertEqual(second['status'], 'nao_iniciado')
        self.assertEqual(self.tree(self.target_u), [])
        text = executor.format_report_pt(result)
        self.assertIn('conferência cancelada', text)
        self.assertNotIn('pode ser retomad', text)
        line = next(item for item in text.splitlines() if item.startswith('- Destino 1'))
        self.assertNotIn('nada foi gravado', line)
        self.assertIn('não conferid', line)
        self.assertEqual(self.source_state(), self.snapshot)

    def test_fix1_cancel_before_check_starts_is_cancelled_not_resumable(self):
        cancelled = threading.Event()
        original = executor.verify_complete_manifest

        def cancel_then_verify(*args, **kwargs):
            cancelled.set()  # verifier raises InterruptedError on its own
            return original(*args, **kwargs)

        with patch.object(executor, 'verify_complete_manifest', cancel_then_verify):
            result = executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs(cancelled=cancelled))
        self.assert_cancelled_during_check(result)

    def test_fix1_cancel_while_hashing_is_cancelled_not_mismatch(self):
        cancelled = threading.Event()
        import selective_recovery

        def cancel_while_hashing(*args, **kwargs):
            cancelled.set()
            raise InterruptedError('synthetic cancel while hashing')

        # The verifier turns this into OSError ("arquivo ausente ou diferente").
        with patch.object(selective_recovery, 'verify_committed_backup_file',
                          cancel_while_hashing):
            result = executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs(cancelled=cancelled))
        self.assert_cancelled_during_check(result)
        self.assertNotIn('ausente ou diferente', result['reason'])

    def recheck_failing_on_second_call(self, error):
        original = executor.recheck_multi_source_preview
        calls = [0]

        def recheck(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise error
            return original(*args, **kwargs)

        return recheck

    def assert_stopped_before_second(self, result):
        self.assertEqual(result['status'], 'parcial')
        self.assertEqual(result['copies_verified'], 1)
        first, second = result['destinations']
        self.assertEqual(first['status'], 'verificado')
        self.assertEqual(second['status'], 'nao_iniciado')
        self.assertIn('desde a prévia', second['problem'])
        self.assertEqual(result['reason'], second['problem'])
        self.assertEqual(self.tree(self.target_u), [])
        text = executor.format_report_pt(result)
        self.assertIn('Motivo da parada', text)
        self.assertIn('Destino 2', text)

    def test_fix2_disk_unavailable_before_second_destination(self):
        recheck = self.recheck_failing_on_second_call(OSError('disco desconectado'))
        with patch.object(executor, 'recheck_multi_source_preview', recheck):
            result = executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs())
        self.assert_stopped_before_second(result)
        self.assertNotIn('A origem mudou', result['reason'])

    def test_fix2_generic_reason_for_any_recheck_value_error(self):
        recheck = self.recheck_failing_on_second_call(
            ValueError('Diagnóstico de discos alterado; refaça a prévia.'))
        with patch.object(executor, 'recheck_multi_source_preview', recheck):
            result = executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs())
        self.assert_stopped_before_second(result)
        self.assertNotIn('A origem mudou', result['reason'])

    def test_fix3_source_changes_after_first_destination_verified(self):
        original = executor.verify_complete_manifest

        def verify_then_change_source(*args, **kwargs):
            outcome = original(*args, **kwargs)
            self.second.write_bytes(b'changed-between-destinations')
            return outcome

        with patch.object(executor, 'verify_complete_manifest',
                          verify_then_change_source):
            result = executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs())
        self.assert_stopped_before_second(result)

    def test_fix4_test_root_must_be_inside_system_temp_folder(self):
        preview = self.preview()
        drive_root = Path(os.path.abspath(os.sep))
        before = self.tree(self.root)
        for bad in (str(drive_root), tempfile.gettempdir()):
            with self.subTest(test_root=bad):
                with self.assertRaisesRegex(ValueError, 'área de teste'):
                    executor.run_protected_copy(
                        self.plan, preview, **self.kwargs(test_root=bad))
        # A folder outside the system temp folder is refused: point the temp
        # folder to a sibling so the sandbox is outside it.
        fake_temp = self.root / 'fake-temp'
        fake_temp.mkdir()
        with patch.object(executor.tempfile, 'gettempdir', lambda: str(fake_temp)):
            for call in (executor.preview_execution, executor.run_protected_copy):
                with self.subTest(call=call.__name__):
                    with self.assertRaisesRegex(ValueError, 'pasta temporária'):
                        call(self.plan, preview, **self.kwargs())
        self.assertEqual(self.tree(self.root), sorted(before + ['fake-temp']))
        self.assert_targets_empty()

    def test_fix5_plan_without_selected_is_a_portuguese_value_error(self):
        broken = SimpleNamespace(files=self.plan.files, warnings=[],
                                 count=self.plan.count, total=self.plan.total)
        for plan in (broken, SimpleNamespace(**dict(vars(broken), selected=None))):
            with self.subTest(selected=getattr(plan, 'selected', 'ausente')):
                with self.assertRaisesRegex(ValueError, 'Plano de origem'):
                    executor.preview_execution(plan, self.preview(), **self.kwargs())
        self.assert_targets_empty()

    # --- 13 --------------------------------------------------------------
    def test_13_app_and_screens_do_not_import_executor(self):
        files = [ROOT / 'app.py', *sorted(ROOT.glob('*_ui.py'))]
        self.assertGreater(len(files), 1)
        for path in files:
            with self.subTest(file=path.name):
                self.assertNotIn('multi_source_executor',
                                 path.read_text(encoding='utf-8'))

    def test_executor_has_no_delete_calls(self):
        code = (ROOT / 'multi_source_executor.py').read_text(encoding='utf-8')
        for word in ('unlink', 'rmtree', 'remove(', 'rmdir', 'os.replace', 'rename'):
            self.assertNotIn(word, code)


if __name__ == '__main__':
    unittest.main()
