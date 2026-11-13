"""P4-03: testes do script de build (PyInstaller), da pasta de dados no modo
empacotado (sys.frozen) e do pacote executável (.exe).

Testes unitários usam apenas TemporaryDirectory e comandos simulados.
O teste do pacote real (dist/PCRestoreOptimizer/PCRestoreOptimizer.exe) roda
apenas com `--smoke-test` (sem tocar em discos reais) e é ignorado (skip)
quando o executável ainda não foi gerado ou fora do Windows.
"""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import choices_store
from scripts import build_exe

ROOT = Path(__file__).resolve().parent.parent
DIST_EXE = ROOT / 'dist' / build_exe.APP_NAME / f'{build_exe.APP_NAME}.exe'


class AppDataDirTests(unittest.TestCase):
    """Confere `choices_store.app_data_dir` nos dois modos (Python e sys.frozen)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_unfrozen_returns_source_directory(self):
        fake_source = self.folder / 'projeto' / 'app.py'
        fake_source.parent.mkdir(parents=True, exist_ok=True)
        fake_source.write_text('# app', encoding='utf-8')
        env = {'LOCALAPPDATA': str(self.folder / 'LocalAppData')}
        result = choices_store.app_data_dir(
            frozen=False, environ=env, source_file=fake_source)
        self.assertEqual(result, fake_source.resolve().parent)

    def test_frozen_returns_localappdata_subdir(self):
        local_appdata = self.folder / 'LocalAppData'
        fake_source = self.folder / 'dist' / '_internal' / 'app.py'
        env = {'LOCALAPPDATA': str(local_appdata)}
        result = choices_store.app_data_dir(
            frozen=True, environ=env, source_file=fake_source)
        self.assertEqual(result, local_appdata / 'PC-Restore-Optimizer')

    def test_sys_frozen_attribute_is_respected_by_default(self):
        local_appdata = self.folder / 'LocalAppData'
        fake_source = self.folder / 'projeto' / 'app.py'
        fake_source.parent.mkdir(parents=True, exist_ok=True)
        env = {'LOCALAPPDATA': str(local_appdata)}
        with mock.patch.object(choices_store.sys, 'frozen', True, create=True):
            frozen_dir = choices_store.app_data_dir(environ=env, source_file=fake_source)
        with mock.patch.object(choices_store.sys, 'frozen', False, create=True):
            normal_dir = choices_store.app_data_dir(environ=env, source_file=fake_source)
        self.assertEqual(frozen_dir, local_appdata / 'PC-Restore-Optimizer')
        self.assertEqual(normal_dir, fake_source.resolve().parent)

    def test_save_merged_creates_missing_parent_dir_in_frozen_mode(self):
        local_appdata = self.folder / 'LocalAppData'
        state_dir = choices_store.app_data_dir(
            frozen=True,
            environ={'LOCALAPPDATA': str(local_appdata)},
            source_file=self.folder / 'app.py',
        )
        prefs_path = state_dir / 'preferencias-v05.json'
        self.assertFalse(state_dir.exists())
        doc = {'choices': {'c:/teste': 'keep'}, 'destination': 'D:/Backups'}
        status, merged, conflicts = choices_store.save_merged(prefs_path, doc, doc)
        self.assertEqual(status, 'ok')
        self.assertEqual(conflicts, [])
        self.assertTrue(prefs_path.is_file())
        self.assertEqual(merged['choices'], {'c:/teste': 'keep'})

    def test_app_and_deep_discovery_use_app_data_dir(self):
        app_src = (ROOT / 'app.py').read_text(encoding='utf-8')
        deep_src = (ROOT / 'deep_discovery_ui.py').read_text(encoding='utf-8')
        self.assertIn(
            "choices_store.app_data_dir(source_file=__file__) / 'preferencias-v05.json'",
            app_src,
        )
        self.assertIn(
            "choices_store.app_data_dir(source_file=__file__) / 'deteccao-detalhada-v065.json'",
            deep_src,
        )


class BuildScriptUnitTests(unittest.TestCase):
    """Confere `scripts/build_exe.py` com diretórios sintéticos e runner falso."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_command_uses_onedir_noconsole_and_no_uac_admin(self):
        cmd = build_exe.build_command(self.folder, python_executable='python3')
        self.assertEqual(cmd[:3], ['python3', '-m', 'PyInstaller'])
        self.assertIn('--onedir', cmd)
        self.assertIn('--noconsole', cmd)
        self.assertIn('--clean', cmd)
        self.assertIn('--noconfirm', cmd)
        self.assertNotIn('--onefile', cmd)
        self.assertNotIn('--uac-admin', cmd)
        self.assertTrue(cmd[-1].endswith('app.py'))

    def test_verify_clean_bundle_detects_personal_and_report_files(self):
        bundle = self.folder / 'dist' / build_exe.APP_NAME
        bundle.mkdir(parents=True)
        (bundle / f'{build_exe.APP_NAME}.exe').write_bytes(b'MZ')
        self.assertEqual(build_exe.verify_clean_bundle(bundle), [])

        (bundle / 'preferencias-v05.json').write_text('{}', encoding='utf-8')
        internal = bundle / '_internal'
        internal.mkdir()
        (internal / 'deteccao-detalhada-v065.json').write_text('{}', encoding='utf-8')
        found = build_exe.verify_clean_bundle(bundle)
        self.assertEqual(len(found), 2)
        self.assertTrue(any('preferencias-v05.json' in item for item in found))
        self.assertTrue(any('deteccao-detalhada-v065.json' in item for item in found))

    def test_run_build_succeeds_with_simulated_pyinstaller(self):
        (self.folder / 'app.py').write_text('print("ok")\n', encoding='utf-8')

        def fake_runner(cmd, cwd=None, check=False):
            exe = Path(cwd) / 'dist' / build_exe.APP_NAME / f'{build_exe.APP_NAME}.exe'
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b'MZ-fake-exe')
            return SimpleNamespace(returncode=0)

        with contextlib.redirect_stdout(io.StringIO()):
            code, exe_path = build_exe.run_build(self.folder, runner=fake_runner)
        self.assertEqual(code, 0)
        self.assertTrue(exe_path.is_file())

    def test_run_build_refuses_bundle_with_personal_preferences(self):
        (self.folder / 'app.py').write_text('print("ok")\n', encoding='utf-8')

        def fake_runner(cmd, cwd=None, check=False):
            bundle = Path(cwd) / 'dist' / build_exe.APP_NAME
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / f'{build_exe.APP_NAME}.exe').write_bytes(b'MZ-fake-exe')
            (bundle / 'preferencias-v05.json').write_text('{}', encoding='utf-8')
            return SimpleNamespace(returncode=0)

        with contextlib.redirect_stdout(io.StringIO()):
            code, _exe_path = build_exe.run_build(self.folder, runner=fake_runner)
        self.assertEqual(code, 1)

    def test_gitignore_and_requirements_build_configured(self):
        gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
        for entry in ('build/', 'dist/', '*.spec'):
            self.assertIn(entry, gitignore)
        req_build = (ROOT / 'requirements-build.txt').read_text(encoding='utf-8')
        self.assertIn('pyinstaller==', req_build.lower())
        req_app = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        self.assertNotIn('pyinstaller', req_app.lower())
        self.assertTrue((ROOT / 'docs' / 'INSTALADOR.md').is_file())


class SmokeTestModeTests(unittest.TestCase):
    """Confere o modo `--smoke-test` no `app.py`."""

    def test_smoke_test_flag_present_in_app_main(self):
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('def _smoke_test():', source)
        self.assertIn("if '--smoke-test' in sys.argv[1:]:", source)
        self.assertIn('raise SystemExit(_smoke_test())', source)


class BuiltExecutableSmokeTests(unittest.TestCase):
    """Teste do pacote real gerado em dist/PCRestoreOptimizer/PCRestoreOptimizer.exe."""

    def setUp(self):
        if os.name != 'nt':
            self.skipTest('Teste do executável (.exe) só roda no Windows.')
        if not DIST_EXE.is_file():
            self.skipTest(
                'Executável dist/PCRestoreOptimizer/PCRestoreOptimizer.exe não foi '
                'gerado neste ambiente (rode py -3 scripts/build_exe.py).'
            )
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        if hasattr(self, '_tmp'):
            self._tmp.cleanup()

    def test_bundle_is_clean_and_exe_opens_and_closes_cleanly(self):
        forbidden = build_exe.verify_clean_bundle(DIST_EXE.parent)
        self.assertEqual(forbidden, [], f'Arquivos proibidos no pacote: {forbidden}')

        env = dict(os.environ)
        env['LOCALAPPDATA'] = str(self.folder / 'LocalAppData')
        result = subprocess.run(
            [str(DIST_EXE), '--smoke-test'],
            cwd=str(self.folder),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode, 0,
            f'O executável falhou ao abrir/fechar (código {result.returncode}): '
            f'{result.stderr[:300]}',
        )
        # O modo --smoke-test não deve gravar preferências nem criar pastas de estado.
        self.assertFalse((self.folder / 'preferencias-v05.json').exists())
        self.assertFalse((self.folder / 'LocalAppData' / 'PC-Restore-Optimizer').exists())


if __name__ == '__main__':
    unittest.main()
