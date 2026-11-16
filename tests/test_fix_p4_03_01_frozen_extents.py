"""FIX-P4-03-01 (fatia 1): consulta de extensões de volume no modo empacotado (.exe).

Tudo sintético: nenhum disco real é consultado. O `runner`/`subprocess.run` e a
função `query` são sempre falsos; arquivos só em TemporaryDirectory.
"""
import ast
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import audit_v069
import child_process
import storage_extents_diagnostic as sd
import volume_extents
from volume_inventory import summarize_volumes

V1 = r'\\?\Volume{12345678-1234-1234-1234-123456789abc}' + '\\'
EXE = r'C:\Programas\PCRO\PC-Restore-Optimizer.exe'


def _simulate_frozen(test, executable=EXE):
    """Simula sys.frozen/sys.executable e restaura no addCleanup (sem mexer em sys.modules)."""
    had_frozen = hasattr(sys, 'frozen')
    old_frozen = getattr(sys, 'frozen', None)
    old_exe = sys.executable

    def restore():
        sys.executable = old_exe
        if had_frozen:
            sys.frozen = old_frozen
        elif hasattr(sys, 'frozen'):
            del sys.frozen
    test.addCleanup(restore)
    sys.frozen = True
    sys.executable = executable


class ExtentsCommandTests(unittest.TestCase):
    def test_python_mode_uses_helper_script_next_to_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'child_process.py'
            cmd = child_process.extents_command(frozen=False, executable='python.exe',
                                                source_file=str(source))
            self.assertEqual(cmd, ['python.exe', str(Path(tmp).resolve() / 'volume_extents.py')])

    def test_frozen_mode_reuses_exe_with_child_flag(self):
        cmd = child_process.extents_command(frozen=True, executable=EXE)
        self.assertEqual(cmd, [EXE, '--pcro-volume-extents'])
        self.assertEqual(child_process.EXTENTS_FLAG, '--pcro-volume-extents')

    def test_defaults_follow_sys(self):
        cmd = child_process.extents_command()
        self.assertEqual(cmd[0], sys.executable)
        if not getattr(sys, 'frozen', False):
            self.assertTrue(cmd[1].endswith('volume_extents.py'))


class FrozenCollectorsTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = summarize_volumes([{'volume_id': V1, 'mount_points': ['F:\\'], 'drive_type': 3}])

    def test_storage_diagnostic_uses_exe_command_and_keeps_timeout(self):
        _simulate_frozen(self)
        captured = {}

        def runner(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            return SimpleNamespace(returncode=0, stdout='[]', stderr='')
        with patch.object(sd, 'os', SimpleNamespace(name='nt')):
            sd.collect_extent_mapping([], snapshot=self.snapshot, runner=runner, timeout=3)
        self.assertEqual(captured['command'], [EXE, '--pcro-volume-extents'])
        self.assertEqual(captured['kwargs']['timeout'], 3)
        self.assertIn('creationflags', captured['kwargs'])

    def test_storage_diagnostic_timeout_in_exe_stays_unknown(self):
        _simulate_frozen(self)

        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 1)
        with patch.object(sd, 'os', SimpleNamespace(name='nt')):
            result = sd.collect_extent_mapping([], snapshot=self.snapshot, runner=runner, timeout=1)
        self.assertEqual(result['status'], 'requires_review')
        self.assertFalse(result['approved_for_format'])
        self.assertEqual(result['volumes'][0]['status'], 'unknown')

    def _evidence(self):
        return {'available': True, 'data': {'legacy_volumes': [
            {'device_id': V1, 'system_volume': False, 'boot_volume': True}]}}

    def test_audit_v069_uses_exe_command_and_keeps_timeout(self):
        _simulate_frozen(self)
        captured = {}

        def fake_run(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            return SimpleNamespace(returncode=0, stdout='[]', stderr='')
        with patch.object(audit_v069, 'collect_disk_evidence_068', return_value=self._evidence()), \
                patch.object(audit_v069.subprocess, 'run', side_effect=fake_run):
            audit_v069.collect_disk_evidence_069()
        self.assertEqual(captured['command'], [EXE, '--pcro-volume-extents'])
        self.assertEqual(captured['kwargs']['timeout'], 25)
        self.assertIn('creationflags', captured['kwargs'])

    def test_audit_v069_timeout_in_exe_is_never_safe(self):
        _simulate_frozen(self)

        def fake_run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 25)
        with patch.object(audit_v069, 'collect_disk_evidence_068', return_value=self._evidence()), \
                patch.object(audit_v069.subprocess, 'run', side_effect=fake_run):
            evidence = audit_v069.collect_disk_evidence_069()
        warnings = evidence['data'].get('warnings', [])
        self.assertTrue(any(w.startswith('Associação direta indisponível') for w in warnings))
        self.assertNotIn('disk_numbers', evidence['data']['legacy_volumes'][0])
        self.assertIsNone(evidence['data'].get('windows_disk_number'))


class DispatchChildTests(unittest.TestCase):
    def test_exact_flag_runs_child_and_returns_zero(self):
        calls = []

        def fake_collect(volumes):
            calls.append(volumes)
            return [{'device_id': V1, 'status': 'unmapped', 'extents': []}]
        stdin = io.StringIO(json.dumps([{'device_id': V1}]))
        stdout = io.StringIO()
        with patch.object(volume_extents, 'collect_extents', side_effect=fake_collect), \
                patch.object(sys, 'stdin', stdin), patch.object(sys, 'stdout', stdout):
            code = child_process.dispatch_child(['--pcro-volume-extents'])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [[{'device_id': V1}]])
        self.assertEqual(json.loads(stdout.getvalue())[0]['device_id'], V1)

    def test_other_arguments_are_not_dispatched(self):
        with patch.object(volume_extents, 'run_child') as run_child:
            for argv in ([], ['--smoke-test'], ['--pcro-volume-extent'],
                         ['--pcro-volume-extents=1'], ['--PCRO-VOLUME-EXTENTS'],
                         ['--pcro-volume-extents', 'extra'], ['x', '--pcro-volume-extents']):
                self.assertIsNone(child_process.dispatch_child(argv), argv)
            run_child.assert_not_called()

    def test_missing_pipes_return_two_without_querying(self):
        with patch.object(volume_extents, 'collect_extents') as collect:
            self.assertEqual(volume_extents.run_child(None, io.StringIO()), 2)
            self.assertEqual(volume_extents.run_child(io.StringIO('[]'), None), 2)
            collect.assert_not_called()

    def test_invalid_input_returns_one_without_querying(self):
        with patch.object(volume_extents, 'collect_extents') as collect:
            for raw in ('nao e json', '{"device_id": "x"}'):
                out = io.StringIO()
                self.assertEqual(volume_extents.run_child(io.StringIO(raw), out), 1)
                self.assertEqual(out.getvalue(), '')
            collect.assert_not_called()

    def test_dispatch_with_no_console_pipes_returns_two(self):
        with patch.object(volume_extents, 'collect_extents') as collect, \
                patch.object(sys, 'stdin', None), patch.object(sys, 'stdout', None):
            self.assertEqual(child_process.dispatch_child(['--pcro-volume-extents']), 2)
        collect.assert_not_called()

    def test_run_child_uses_injected_query_only(self):
        stdout = io.StringIO()
        code = volume_extents.run_child(io.StringIO(json.dumps([{'device_id': V1}])), stdout,
                                        query=lambda _id: [{'disk_number': 1, 'starting_offset': 0,
                                                            'extent_length': 4096}])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())[0]['status'], 'mapped')

    def test_child_process_has_no_tkinter_import(self):
        tree = ast.parse(Path(child_process.__file__).read_text(encoding='utf-8'))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split('.')[0])
        self.assertNotIn('tkinter', names)
        self.assertIn('volume_extents', names)  # o PyInstaller precisa ver este import

    def test_app_main_dispatches_before_smoke_test_and_window(self):
        source = Path(audit_v069.__file__).with_name('app.py').read_text(encoding='utf-8')
        main = source[source.index("if __name__=='__main__':"):]
        self.assertIn('dispatch_child(sys.argv[1:])', main)
        self.assertLess(main.index('dispatch_child'), main.index('--smoke-test'))
        self.assertLess(main.index('dispatch_child'), main.index('App()'))


if __name__ == '__main__':
    unittest.main()
