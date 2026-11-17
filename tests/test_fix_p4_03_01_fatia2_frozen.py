"""FIX-P4-03-01 (fatia 2): ajustes do modo empacotado (.exe), sem tocar em discos reais.

Tudo sintético: `sys.frozen` é simulado e restaurado no fim de cada teste (sem
mexer em `sys.modules`), `subprocess.Popen`/`subprocess.run` são falsos e os
arquivos ficam só em TemporaryDirectory.
"""
import ast
import builtins
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import audit_v069
import autotestes_escala
import choices_store
import storage_extents_diagnostic as sd
import volume_extents
from volume_inventory import summarize_volumes

V1 = r'\\?\Volume{12345678-1234-1234-1234-123456789abc}' + '\\'
APP_PY = Path(audit_v069.__file__).with_name('app.py')
EMPTY_ERROR = ('Não foi possível consultar em que disco está cada volume; '
               'trate como não confirmado.')


def _simulate_frozen(test, value=True):
    """Simula (ou remove) sys.frozen e restaura o valor original no addCleanup."""
    had_frozen = hasattr(sys, 'frozen')
    old_frozen = getattr(sys, 'frozen', None)

    def restore():
        if had_frozen:
            sys.frozen = old_frozen
        elif hasattr(sys, 'frozen'):
            del sys.frozen
    test.addCleanup(restore)
    if value:
        sys.frozen = True
    elif hasattr(sys, 'frozen'):
        del sys.frozen


class ScaleAutotestFrozenTests(unittest.TestCase):
    """(a) No .exe o autoteste de escala recusa o padrão `--child` em vez de reabrir o programa."""

    def _no_process(self, *args, **kwargs):
        raise AssertionError('Nenhum processo pode ser iniciado no .exe.')

    def test_frozen_refuses_before_creating_anything(self):
        _simulate_frozen(self)
        for runner in (autotestes_escala.run_gigabyte_autotest,
                       autotestes_escala.run_abrupt_exit_autotest):
            with patch.object(autotestes_escala.subprocess, 'Popen', side_effect=self._no_process), \
                    patch.object(autotestes_escala, 'private_root',
                                 side_effect=AssertionError('não deve criar pasta')):
                with self.assertRaises(RuntimeError) as ctx:
                    runner()
            self.assertEqual(str(ctx.exception), autotestes_escala.FROZEN_REFUSAL)

    def test_frozen_launch_never_starts_process(self):
        _simulate_frozen(self)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(autotestes_escala.subprocess, 'Popen', side_effect=self._no_process):
            with self.assertRaises(RuntimeError) as ctx:
                autotestes_escala.launch(Path(tmp), 'token', 'large')
            self.assertFalse((Path(tmp) / 'child.log').exists())
        self.assertIn('programa instalado', str(ctx.exception))
        self.assertIn('nada foi aprovado', str(ctx.exception))

    def test_python_mode_still_uses_child_pattern(self):
        _simulate_frozen(self, value=False)
        captured = {}

        class FakeProcess:
            returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        def fake_popen(command, **kwargs):
            captured['command'] = command
            return FakeProcess()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(autotestes_escala.subprocess, 'Popen', side_effect=fake_popen):
            code = autotestes_escala.launch(Path(tmp), 'token', 'large')
        self.assertEqual(code, 0)
        self.assertEqual(captured['command'][1:3],
                         [str(Path(autotestes_escala.__file__).resolve()), '--child'])


class DataFileCandidatesTests(unittest.TestCase):
    """(b) O app lê `deteccao-detalhada-v0514.json` da pasta de dados, com o local antigo só para leitura."""

    def test_python_mode_is_only_the_source_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'app.py'
            found = choices_store.data_file_candidates('deteccao-detalhada-v0514.json', frozen=False,
                                                       environ={'LOCALAPPDATA': tmp}, source_file=str(source))
            self.assertEqual(found, [Path(tmp).resolve() / 'deteccao-detalhada-v0514.json'])

    def test_frozen_mode_prefers_data_folder_then_old_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / 'programa' / '_internal'
            local = Path(tmp) / 'local'
            found = choices_store.data_file_candidates('deteccao-detalhada-v0514.json', frozen=True,
                                                       environ={'LOCALAPPDATA': str(local)},
                                                       source_file=str(program / 'app.py'))
            self.assertEqual(found, [local / 'PC-Restore-Optimizer' / 'deteccao-detalhada-v0514.json',
                                     program.resolve() / 'deteccao-detalhada-v0514.json'])

    def test_reading_old_file_never_moves_or_deletes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / 'programa'
            program.mkdir()
            old = program / 'deteccao-detalhada-v0514.json'
            old.write_text(json.dumps({'schema': 'pcro-discovery-v1', 'records': []}), encoding='utf-8')
            before = old.read_bytes()
            report = choices_store.read_first_json(choices_store.data_file_candidates(
                'deteccao-detalhada-v0514.json', frozen=True,
                environ={'LOCALAPPDATA': str(Path(tmp) / 'local')}, source_file=str(program / 'app.py')))
            self.assertEqual(report['schema'], 'pcro-discovery-v1')
            self.assertEqual(old.read_bytes(), before)
            self.assertFalse((Path(tmp) / 'local').exists())

    def test_new_location_wins_and_bad_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second, third = (Path(tmp) / n for n in ('a.json', 'b.json', 'c.json'))
            first.write_text('{quebrado', encoding='utf-8')
            second.write_text(json.dumps({'schema': 'pcro-discovery-v1', 'origem': 'b'}), encoding='utf-8')
            third.write_text(json.dumps({'schema': 'pcro-discovery-v1', 'origem': 'c'}), encoding='utf-8')
            missing = Path(tmp) / 'nao-existe.json'
            self.assertEqual(choices_store.read_first_json([missing, first, second, third])['origem'], 'b')
            self.assertIsNone(choices_store.read_first_json([missing, first]))
            third.write_text(json.dumps({'schema': 'outro', 'origem': 'c'}), encoding='utf-8')
            self.assertEqual(choices_store.read_first_json([third, second], schema='pcro-discovery-v1')['origem'], 'b')
            self.assertIsNone(choices_store.read_first_json([third], schema='pcro-discovery-v1'))

    def test_app_reads_v0514_through_data_folder(self):
        source = APP_PY.read_text(encoding='utf-8')
        self.assertNotIn("Path(__file__).parent/'deteccao-detalhada-v0514.json'", source)
        self.assertIn("data_file_candidates('deteccao-detalhada-v0514.json'", source)


class ProgramDirsTests(unittest.TestCase):
    """(c) Exclusões da varredura e pasta da otimização no .exe."""

    def test_python_mode_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'deep_discovery_ui.py'
            dirs = choices_store.program_dirs(frozen=False, environ={'LOCALAPPDATA': tmp},
                                              source_file=str(source), executable='python.exe')
            self.assertEqual(dirs, [str(Path(tmp).resolve())])

    def test_frozen_mode_adds_exe_folder_and_data_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'PCRestoreOptimizer'
            internal = base / '_internal'
            local = Path(tmp) / 'local'
            dirs = choices_store.program_dirs(frozen=True, environ={'LOCALAPPDATA': str(local)},
                                              source_file=str(internal / 'deep_discovery_ui.py'),
                                              executable=str(base / 'PCRestoreOptimizer.exe'))
            self.assertEqual(dirs, [str(internal.resolve()), str(base.resolve()),
                                    str((local / 'PC-Restore-Optimizer').resolve())])

    def test_frozen_mode_never_excludes_a_drive_root_or_the_home_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            internal = Path(tmp) / 'x' / '_internal'
            home = Path(tmp) / 'home'
            for exe_dir in (Path(Path(tmp).anchor), home, home.parent):
                with patch.object(choices_store.Path, 'home', return_value=home):
                    dirs = choices_store.program_dirs(frozen=True, environ={'LOCALAPPDATA': str(Path(tmp) / 'l')},
                                                      source_file=str(internal / 'm.py'),
                                                      executable=str(exe_dir / 'PCRO.exe'))
                self.assertNotIn(str(exe_dir.resolve()), dirs, exe_dir)
                self.assertIn(str(internal.resolve()), dirs)

    def test_deep_discovery_ui_uses_program_dirs(self):
        source = Path(audit_v069.__file__).with_name('deep_discovery_ui.py').read_text(encoding='utf-8')
        self.assertNotIn('str(Path(__file__).resolve().parent)', source)
        self.assertEqual(source.count('choices_store.program_dirs(source_file=__file__)'), 2)

    def test_optimization_panel_receives_data_folder(self):
        source = APP_PY.read_text(encoding='utf-8')
        self.assertIn('OptimizationPanel(self.optimization, app_dir=choices_store.app_data_dir(source_file=__file__))',
                      source)


class ChildStderrTests(unittest.TestCase):
    """(d) e (e): stderr ilegível ou vazio do filho nunca vira "seguro" nem texto vazio."""

    def setUp(self):
        self.snapshot = summarize_volumes([{'volume_id': V1, 'mount_points': ['F:\\'], 'drive_type': 3}])

    def _evidence(self):
        return {'available': True, 'data': {'legacy_volumes': [
            {'device_id': V1, 'system_volume': False, 'boot_volume': True}]}}

    def test_audit_v069_decodes_stderr_with_replace(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured.update(kwargs)
            # Bytes cp1252 decodificados como utf-8 com errors='replace'.
            text = 'Entrada inv\xe1lida'.encode('cp1252').decode(kwargs['encoding'], kwargs['errors'])
            return SimpleNamespace(returncode=1, stdout='', stderr=text)
        with patch.object(audit_v069, 'collect_disk_evidence_068', return_value=self._evidence()), \
                patch.object(audit_v069.subprocess, 'run', side_effect=fake_run):
            evidence = audit_v069.collect_disk_evidence_069()
        self.assertEqual(captured['errors'], 'replace')
        self.assertEqual(captured['encoding'], 'utf-8')
        warnings = evidence['data']['warnings']
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith('Associação direta indisponível: Consulta de volumes não concluída: Entrada inv'))
        self.assertNotIn('disk_numbers', evidence['data']['legacy_volumes'][0])

    def test_audit_v069_empty_stderr_has_clear_text(self):
        def fake_run(command, **kwargs):
            return SimpleNamespace(returncode=1, stdout='', stderr='')
        with patch.object(audit_v069, 'collect_disk_evidence_068', return_value=self._evidence()), \
                patch.object(audit_v069.subprocess, 'run', side_effect=fake_run):
            evidence = audit_v069.collect_disk_evidence_069()
        self.assertEqual(evidence['data']['warnings'], ['Associação direta indisponível: ' + EMPTY_ERROR])
        self.assertIsNone(evidence['data'].get('windows_disk_number'))

    def test_storage_diagnostic_empty_stderr_has_clear_text(self):
        for stderr in ('', '   \n', None):
            def runner(command, stderr=stderr, **kwargs):
                return SimpleNamespace(returncode=1, stdout='', stderr=stderr)
            with patch.object(sd, 'os', SimpleNamespace(name='nt')):
                result = sd.collect_extent_mapping([], snapshot=self.snapshot, runner=runner, timeout=3)
            self.assertEqual(result['status'], 'requires_review')
            self.assertFalse(result['approved_for_format'])
            self.assertEqual(result['volumes'][0]['status'], 'unknown')
            self.assertIn('Consulta de extensões indisponível: ' + EMPTY_ERROR, result['issues'])
            self.assertFalse(any(i.rstrip().endswith('Consulta retornou erro:') for i in result['issues']))

    def test_storage_diagnostic_keeps_child_message_when_present(self):
        def runner(command, **kwargs):
            return SimpleNamespace(returncode=1, stdout='', stderr='Erro no processo filho: ValueError')
        with patch.object(sd, 'os', SimpleNamespace(name='nt')):
            result = sd.collect_extent_mapping([], snapshot=self.snapshot, runner=runner, timeout=3)
        self.assertIn('Consulta de extensões indisponível: Consulta retornou erro: '
                      'Erro no processo filho: ValueError', result['issues'])


class AppTopDispatchTests(unittest.TestCase):
    """(f) O modo filho é atendido no topo de app.py, antes dos imports pesados."""

    def test_dispatch_is_before_tkinter_and_disks(self):
        tree = ast.parse(APP_PY.read_text(encoding='utf-8'))
        body = tree.body
        dispatch_at = next(i for i, node in enumerate(body)
                           if isinstance(node, ast.If) and 'dispatch_child' in ast.unparse(node))
        heavy_at = next(i for i, node in enumerate(body)
                        if (isinstance(node, (ast.Import, ast.ImportFrom)) and 'tkinter' in ast.unparse(node))
                        or (isinstance(node, ast.Assign) and 'discover_drive_letters' in ast.unparse(node)))
        self.assertLess(dispatch_at, heavy_at)
        for node in body[:dispatch_at]:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.assertIn(ast.unparse(node), ('import sys',))
        guard = ast.unparse(body[dispatch_at].test)
        self.assertIn('__name__', guard)
        self.assertIn('__main__', guard)
        self.assertEqual(APP_PY.read_text(encoding='utf-8').count('dispatch_child(sys.argv[1:])'), 1)

    def test_child_mode_exits_without_importing_tkinter(self):
        # Executa o app.py de verdade como __main__ com o argumento do filho; a consulta
        # é falsa. Se chegasse ao `import tkinter` ou a `runtime_volumes`, o import
        # falso falharia e o teste veria outro erro em vez de SystemExit(0).
        calls = []

        def fake_child(stdin, stdout):
            calls.append(True)
            return 0
        old_argv = sys.argv
        self.addCleanup(setattr, sys, 'argv', old_argv)
        sys.argv = [str(APP_PY), '--pcro-volume-extents']
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            # Barra os imports pesados: nada de janela nem de consulta de unidades reais.
            if name.split('.')[0] in ('tkinter', 'runtime_volumes'):
                raise AssertionError('import pesado antes do modo filho: ' + name)
            return real_import(name, *args, **kwargs)
        with patch.object(volume_extents, 'run_child', side_effect=fake_child), \
                patch.object(builtins, '__import__', side_effect=guarded_import):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(str(APP_PY), run_name='__main__')
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(calls, [True])

    def test_import_as_module_does_not_dispatch(self):
        source = APP_PY.read_text(encoding='utf-8')
        top = source[:source.index('import tkinter')]
        self.assertIn("if __name__ == '__main__':", top)


if __name__ == '__main__':
    unittest.main()
