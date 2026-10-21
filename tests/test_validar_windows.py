"""scripts/validar_windows.py against a throwaway local git remote (synthetic only)."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which('git')


def load_module():
    spec = importlib.util.spec_from_file_location('validar_windows', ROOT / 'scripts' / 'validar_windows.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(GIT, 'git não instalado')
class ValidarWindowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            'GIT_AUTHOR_NAME': 'Teste', 'GIT_AUTHOR_EMAIL': 'teste@example.invalid',
            'GIT_COMMITTER_NAME': 'Teste', 'GIT_COMMITTER_EMAIL': 'teste@example.invalid',
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'})
        self.env.start()
        self.remote = base / 'remote.git'
        self.repo = base / 'repo'
        run = lambda *a, cwd=base: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)
        run('init', '-q', '--bare', '-b', 'main', str(self.remote))
        run('init', '-q', '-b', 'main', str(self.repo))
        (self.repo / 'tests').mkdir()
        (self.repo / 'a.txt').write_text('a')
        run('add', '.', cwd=self.repo)
        run('commit', '-q', '-m', 'base', cwd=self.repo)
        run('remote', 'add', 'origin', str(self.remote), cwd=self.repo)
        run('push', '-q', 'origin', 'main', cwd=self.repo)
        run('switch', '-q', '-c', 'fix/exemplo', cwd=self.repo)
        (self.repo / 'b.txt').write_text('b')
        run('add', '.', cwd=self.repo)
        run('commit', '-q', '-m', 'fix', cwd=self.repo)
        run('push', '-q', 'origin', 'fix/exemplo', cwd=self.repo)
        run('push', '-q', 'origin', 'main:outro/ignorado', cwd=self.repo)
        self.mod = load_module()
        self.mod.ROOT = self.repo
        # Safety net: every git call must hit the throwaway repo, never the real one.
        real_git = self.mod.git

        def guarded(*args, cwd=None, check=True):
            target = Path(cwd or self.mod.ROOT).resolve()
            allowed = (str(target).startswith(str(base.resolve()))
                       or Path(target).name.startswith(('resultados-wt', 'wt-'))
                       and Path(target).parent.name.startswith('pcro-validacao-'))
            self.assertTrue(allowed, target)
            return real_git(*args, cwd=cwd, check=check)
        self.mod.git = guarded

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_runs_pending_branches_and_publishes_sanitized_results(self):
        log = 'Ran 3 tests in 0.1s\nOK\nC:\\Users\\fulano\\x.py token=abc123\n'
        with mock.patch.object(self.mod, 'run_suite', return_value=(0, log)) as suite, \
                mock.patch.object(self.mod, 'is_elevated', return_value=False):
            self.assertEqual(self.mod.main([]), 0)
            self.assertEqual(suite.call_count, 2)  # main + fix/exemplo; outro/ ignorado
            self.assertEqual(self.mod.main([]), 0)  # second run: already validated
            self.assertEqual(suite.call_count, 2)
        files = subprocess.run(['git', 'ls-tree', '-r', '--name-only', 'validacao-windows'],
                               cwd=self.remote, capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(len([f for f in files if f.startswith('resultados/main/')]), 1)
        self.assertEqual(len([f for f in files if f.startswith('resultados/fix_exemplo/')]), 1)
        content = subprocess.run(['git', 'show', f"validacao-windows:{[f for f in files if 'fix_exemplo' in f][0]}"],
                                 cwd=self.remote, capture_output=True, text=True, check=True).stdout
        self.assertIn('PASSOU', content)
        self.assertNotIn('fulano', content)
        self.assertNotIn('abc123', content)
        # The user's own checkout is untouched.
        branch = subprocess.run(['git', 'branch', '--show-current'], cwd=self.repo,
                                capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, 'fix/exemplo')

    def test_refuses_elevated_terminal(self):
        with mock.patch.object(self.mod, 'is_elevated', return_value=True), \
                mock.patch.object(self.mod, 'run_suite') as suite:
            self.assertEqual(self.mod.main([]), 2)
            suite.assert_not_called()


if __name__ == '__main__':
    unittest.main()
