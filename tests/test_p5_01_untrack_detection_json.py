"""P5-01 fatia 1: o inventário pessoal `deteccao-detalhada-v0*.json` fica fora do git.

Só arquivos sintéticos em TemporaryDirectory; o PyInstaller é simulado.
"""
from __future__ import annotations

import fnmatch
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _load_build_exe():
    spec = importlib.util.spec_from_file_location('build_exe_p5_01', ROOT / 'scripts' / 'build_exe.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gitignore_patterns() -> list[str]:
    lines = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith('#')]


class GitignoreCoversDetectionJson(unittest.TestCase):
    def test_pattern_present(self):
        self.assertIn('deteccao-detalhada-v0*.json', _gitignore_patterns())

    def test_pattern_matches_all_known_versions(self):
        patterns = _gitignore_patterns()
        for name in ('deteccao-detalhada-v065.json', 'deteccao-detalhada-v064.json',
                     'deteccao-detalhada-v0514.json', 'deteccao-detalhada-v060.json'):
            with self.subTest(name=name):
                self.assertTrue(any(fnmatch.fnmatch(name, p) for p in patterns))

    @unittest.skipUnless(shutil.which('git') and (ROOT / '.git').exists(), 'git indisponível')
    def test_not_tracked(self):
        result = subprocess.run(['git', 'ls-files', '--', 'deteccao-detalhada-*.json'],
                                cwd=str(ROOT), capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '')


class BuildWorksWithoutDetectionJson(unittest.TestCase):
    def setUp(self):
        self.build_exe = _load_build_exe()

    def _fake_project(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / 'app.py').write_text('print("app")\n', encoding='utf-8')
        return root

    def _runner_creating_exe(self, root: Path, extra: dict[str, str] | None = None):
        app = self.build_exe.APP_NAME

        def runner(cmd, cwd=None, check=False):
            out = root / 'dist' / app
            out.mkdir(parents=True, exist_ok=True)
            (out / f'{app}.exe').write_bytes(b'MZ')
            for name, text in (extra or {}).items():
                (out / name).write_text(text, encoding='utf-8')
            return types.SimpleNamespace(returncode=0)
        return runner

    def test_build_without_json_in_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_project(tmp)
            self.assertFalse(any(root.glob('deteccao-detalhada-*.json')))
            code, exe = self.build_exe.run_build(root, runner=self._runner_creating_exe(root),
                                                 python_executable='python-sintetico')
            self.assertEqual(code, 0)
            self.assertTrue(exe.is_file())

    def test_command_never_references_detection_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_project(tmp)
            (root / 'deteccao-detalhada-v065.json').write_text('{}', encoding='utf-8')
            cmd = self.build_exe.build_command(root, python_executable='python-sintetico')
            self.assertFalse(any('deteccao-detalhada' in part for part in cmd))

    def test_new_detection_version_still_refused_in_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_project(tmp)
            runner = self._runner_creating_exe(root, {'deteccao-detalhada-v099.json': '{}'})
            code, _exe = self.build_exe.run_build(root, runner=runner,
                                                  python_executable='python-sintetico')
            self.assertEqual(code, 1)

    def test_forbidden_name_helper_covers_any_version(self):
        self.assertTrue(self.build_exe.is_personal_data_file('deteccao-detalhada-v099.json'))
        self.assertTrue(self.build_exe.is_personal_data_file('Preferencias-v05.json'))
        self.assertFalse(self.build_exe.is_personal_data_file('app.py'))


if __name__ == '__main__':
    unittest.main()
